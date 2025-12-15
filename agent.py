from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from langchain_google_vertexai import ChatVertexAI
import vertexai
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest
from langchain_community.chat_message_histories.firestore import FirestoreChatMessageHistory

import os
from dotenv import load_dotenv

load_dotenv()

project_id = os.getenv('GOOGLE_PROJECT_ID', 'dash-beta-e61d0')
location = os.getenv('GOOGLE_LOCATION', 'europe-west1')
vertexai.init(project=project_id, location=location)

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
            "max_output_tokens": 1000,
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

    def _get_message_history(self, user_id: str, session_id: str):
        """Create Firestore history for a specific user/session"""
        return FirestoreChatMessageHistory(
            collection_name='messages',
            session_id=session_id,
            user_id=user_id
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
        """Extract plain text from structured content"""
        if isinstance(content, str):
            return content
        
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            return '\n\n'.join(text_parts) if text_parts else str(content)
        
        return str(content)
    
    def invoke(self, query: str, user_id: str = None, session_id: str = None):
        user_id = user_id or "CORZZX0MxTQtGyAD7PSCI1HLp3y2"
        session_id = session_id or "user_id_randint"

        message_history = self._get_message_history(user_id, session_id)
        message_history.add_user_message(query)
        
        full_history = message_history.messages
        formatted_history = [
            {"role": msg.type, "content": msg.content}
            for msg in full_history[-self.max_messages:]
        ]

        result = self.agent.invoke({"messages": formatted_history})
        
        # Extract text response
        response_content = self._extract_text_content(result["messages"][-1].content)
        
        # Store as plain text in Firestore
        message_history.add_ai_message(response_content)
        
        return response_content