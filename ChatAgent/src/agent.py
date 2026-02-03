from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from langchain_google_vertexai import ChatVertexAI
import vertexai
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest
from firestore import FireStoreChat

import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

project_id = os.getenv('GOOGLE_PROJECT_ID', 'dash-beta-e61d0')
location = os.getenv('GOOGLE_LOCATION', 'europe-west1')
vertexai.init(project=project_id, location=location)

class EmptyLLMResponseError(Exception):
    pass

class agent:
    def __init__(self, model_name: str,  system_prompt: str, tool_set, search_input):
        self.basic_model = model_name
        self.advanced_model = "gemini-2.5-pro"

        self.tool_list = tool_set
        self.system_prompt = system_prompt
        self.search_input = search_input

        # Set a limit on how many last messages we inject (limit short term memory)
        self.max_messages = 20

        # Safety - content filter configuration
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        }

        self.model_kwargs = {
            # Temperature - degree of randomness
            "temperature": 1.0, 
            # Max output tokens - limit max text output from one promp
            "max_output_tokens": 8192,
            # Top p - select x tokens till sum of probability = top_p
            "top_p": 0.95,
            # Top k - next token selected among top-k 
            "top_k": None,
            "safety_settings": self.safety_settings
        }

        # Enable switching to pro model 
        @wrap_model_call
        def _model_selection(request: ModelRequest, handler):
            """Choose model based on conversation complexity"""
            message_count = len(request.state["messages"])

            # Choose larger model for longer conversations 
            if message_count > 10:
                # print(f"Selecting Advanced Model ({self.advanced_model})")
                model_name = self.advanced_model
            else:
                # print(f"Selecting Basic Model ({self.basic_model})")
                model_name = self.basic_model
            
            # Bind model to google search
            model = ChatVertexAI(
                model_name=model_name,
                temperature=self.model_kwargs.get('temperature'),
                max_tokens=self.model_kwargs.get('max_output_tokens'),
                top_p=self.model_kwargs.get('top_p'),
                top_k=self.model_kwargs.get('top_k'),
                # safety_settings=model_kwargs.get('safety_settings'),
            ).bind_tools(self.tool_list)

            return handler(request.override(model=model))

        self._model_selection = _model_selection
        self.llm = self._create_llm()
        self.agent = self._create_agent(self.llm)

    def _init_FireStore(self, user_id: str, session_id: str = None):
        """Initialise Firestore to obtain chat history or user info for a specific user/session"""
        return FireStoreChat(
            user_id=user_id,
            session_id=session_id
        )
    
    def _create_llm(self):
        llm = ChatVertexAI(
            model_name=self.basic_model,
            temperature=self.model_kwargs.get('temperature'),
            max_tokens=self.model_kwargs.get('max_output_tokens'),
            top_p=self.model_kwargs.get('top_p'),
            top_k=self.model_kwargs.get('top_k'),
            # safety_settings=model_kwargs.get('safety_settings'),
        ).bind_tools(self.tool_list)

        return llm

    def _create_agent(self, llm):
        # Create agent
        agent = create_agent(
            llm,
            tools=self.tool_list,
            system_prompt=self.system_prompt,
            context_schema=self.search_input,
            middleware=[self._model_selection],
        )
        return agent

    def _extract_text_content(self, content):
        """Try to extract JSON dictionary, fallback to structured text"""
        
        # Convert complex content (list/blocks) to a single string first
        raw_string = ""
        if isinstance(content, str):
            raw_string = content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            raw_string = '\n\n'.join(text_parts)
        else:
            raw_string = str(content)

        # Attempt to extract and parse JSON from the raw_string
        # This regex finds the first '{' and the last '}'
        json_match = re.search(r'(\{.*\})', raw_string, re.DOTALL)
        
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                # If it looks like JSON but is broken, return as a message
                pass

        # Fallback: If no JSON is found, return the text in the required schema
        return {
            "message": raw_string,
            "ui_actions": []
        }
    
    def _get_daily_session_id(self, user_id: str) -> str:
        """Create one session per day"""
        today = datetime.now().strftime('%Y%m%d')
        return f"{today}"
    
    def _get_session_summary(self, firestore: FireStoreChat, session_id: str = None) -> str:
        """ Retrieve all previous sessions for this user and summarise each into a single output"""
        data = firestore.load_all_messages(current_session_id=session_id)
        
        out = self.llm.invoke(f"You are a helpful assistant that summarises conversations briefly, incorporating all important information from the conversation. Focus on key topics discussed, important user preferences, and any ongoing context. Summarise the following: {data}")
        summary = out.content if hasattr(out, 'content') else str(out)

        return summary
    
    def invoke_res(self, query: str, user_id: str = None, session_id: str = None):
        max_retries = 2
        session_id = self._get_daily_session_id(user_id)

        firestore = self._init_FireStore(user_id, session_id)
        
        firestore.add_user_message(query)
        
        # History containing only messages from current session
        full_history = firestore.load_messages()

        # Limited short term memory 
        recent_messages = [
            {"role": msg.type, "content": msg.content}
            for msg in full_history[-self.max_messages:]
        ]

        # Long term summary and user context injection in a stateless way - only if not already present
        if len(full_history) <= 1:  # Only the query we just added
            # Load or generate summary from previous sessions
            summary = self._get_session_summary(firestore, session_id)
            user_context = firestore.get_user_context()
            
            recent_messages = [
                {"role": "system", "content": user_context},
                {"role": "system", "content": summary},
                *recent_messages
            ]
            print("Injected user context and session summary into recent messages.")
        
        # Extract text response
        for attempt in range(max_retries):
            try:
                result = self.agent.invoke({"messages": recent_messages})
                print(result)
                if result.get("finish_reason") == "MALFORMED_FUNCTION_CALL":
                    raise RuntimeError("Tool call failed due to malformed arguments")
                
                response_content = self._extract_text_content(result["messages"][-1].content)
                
                if response_content:
                    break

                raise EmptyLLMResponseError()
            
            except EmptyLLMResponseError as e:
                if attempt == max_retries-1:
                    response_content = "I could not generate a response. Please try again"
        
        # Store as plain text in Firestore if response is non empty to avoid InvalidArg error
        if response_content:
            # 1. Decide what to store in Firestore history
            if isinstance(response_content, dict):
                # Store just the text message so the AI can read its history later
                db_text = response_content.get("message", "Data response sent.")
                firestore.add_ai_message(db_text)
            else:
                # Fallback if it somehow returned a string
                firestore.add_ai_message(str(response_content))
        
        return response_content