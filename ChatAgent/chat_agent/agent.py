from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from langchain_google_vertexai import ChatVertexAI
import vertexai
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest
from chat_agent.firestore import FireStoreChat

import os
import json
import re
import time
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

project_id = os.getenv('GOOGLE_PROJECT_ID', 'dash-beta-e61d0')
location = os.getenv('GOOGLE_LOCATION', 'europe-west1')
vertexai.init(project=project_id, location=location)
location_global = 'global'

class EmptyLLMResponseError(Exception):
    pass

class agent:
    def __init__(self, model_name: str,  system_prompt: str, tool_set, search_input):
        self.basic_model = model_name
        self.advanced_model = "gemini-3.1-pro-preview"

        self.tool_list = tool_set
        self.system_prompt = system_prompt
        self.search_input = search_input

        # Set a limit on how many last messages we inject (limit short term memory)
        self.max_messages = 5

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
        
        # --- Optimisation: Pre-initialize models ---
        # Initialize models once and reuse them to avoid client creation latency on every request.
        self.basic_llm = ChatVertexAI(
            model_name=self.basic_model,
            temperature=self.model_kwargs.get('temperature'),
            max_tokens=self.model_kwargs.get('max_output_tokens'),
            top_p=self.model_kwargs.get('top_p'),
            top_k=self.model_kwargs.get('top_k'),
            location="global"
        ).bind_tools(self.tool_list)

        self.advanced_llm = ChatVertexAI(
            model_name=self.advanced_model,
            temperature=self.model_kwargs.get('temperature'),
            max_tokens=self.model_kwargs.get('max_output_tokens'),
            top_p=self.model_kwargs.get('top_p'),
            top_k=self.model_kwargs.get('top_k'),
            location="global"
        ).bind_tools(self.tool_list)

        # Use Flash for summaries to save time and cost
        self.summary_llm = ChatVertexAI(
            model_name="gemini-3-flash-preview",
            temperature=0.0, # Deterministic for summaries
            location="global"
        )

        # Enable switching to pro model 
        @wrap_model_call
        async def _amodel_selection(request: ModelRequest, handler):
            """Choose model based on conversation complexity"""
            message_count = len(request.state["messages"])

            # Choose larger model for longer conversations 
            if message_count > 10:
                model = self.advanced_llm
            else:
                model = self.basic_llm

            return await handler(request.override(model=model))

        @wrap_model_call
        def _model_selection(request: ModelRequest, handler):
            """Choose model based on conversation complexity"""
            message_count = len(request.state["messages"])

            # Choose larger model for longer conversations 
            if message_count > 10:
                model = self.advanced_llm
            else:
                model = self.basic_llm

            return handler(request.override(model=model))

        self._model_selection = _amodel_selection
        self.llm = self.basic_llm # Use basic_llm
        self.agent = self._create_agent(self.llm)

    def _init_FireStore(self, user_id: str, session_id: str = None):
        """Initialise Firestore to obtain chat history or user info for a specific user/session"""
        return FireStoreChat(
            user_id=user_id,
            session_id=session_id
        )
    
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
    
    async def _ainvoke_llm(self, prompt: str, use_summary_model=False):
        """Async call to the LLM"""
        llm = self.summary_llm if use_summary_model else self.llm
        out = await llm.ainvoke(prompt)
        if hasattr(out, 'content'):
            return out.content
        return str(out)

    async def _aget_session_summary(self, firestore: FireStoreChat, session_id: str = None) -> str:
        """ Retrieve all previous sessions for this user and summarise each into a single output"""
        load_start = time.perf_counter()
        # 1. Get list of sessions
        sessions = await asyncio.to_thread(firestore.load_session_list)
        
        # 2. Load all sessions in parallel
        tasks = []
        for s in sessions:
            if s.id != session_id:
                tasks.append(asyncio.to_thread(firestore.load_messages_by_id, s.id))
        
        if not tasks:
            return ""
            
        all_session_data = await asyncio.gather(*tasks)
        # Flatten the list of lists
        data = [msg for session_list in all_session_data for msg in session_list]
        print(f"[Profiling] Firestore Parallel Load ({len(tasks)} sessions) took {time.perf_counter() - load_start:.2f}s")
        
        if not data:
            return ""

        summary_start = time.perf_counter()
        summary = await self._ainvoke_llm(
            f"You are a helpful assistant that summarises conversations briefly, incorporating all important information from the conversation. Focus on key topics discussed, important user preferences, and any ongoing context. Summarise the following: {data}",
            use_summary_model=True
        )
        print(f'[Profiling] Summary generation (Flash) took {time.perf_counter() - summary_start:.2f}s')
        return summary
    
    async def ainvoke_res(self, query: str, user_id: str = None, session_id: str = None):
        total_start = time.perf_counter()
        max_retries = 2
        session_id = self._get_daily_session_id(user_id)

        # Initialize Firestore for the current user and session
        firestore = self._init_FireStore(user_id, session_id)
        
        # Set status: Loading history
        await asyncio.to_thread(firestore.set_status, "history")

        # Check if this is the first message in the session to inject context
        step_start = time.perf_counter()
        current_session_history = await asyncio.to_thread(firestore.load_messages)
        is_new_session = len(current_session_history) == 0
        print(f"[Profiling] Firestore load_messages took {time.perf_counter() - step_start:.2f}s")

        if is_new_session:
            print("New session detected. Injecting user context and session summary.")
            
            # Set status: Summarizing
            await asyncio.to_thread(firestore.set_status, "summary")

            step_start = time.perf_counter()
            # Run user context fetch and summary generation concurrently
            user_context_task = asyncio.to_thread(firestore.get_user_context)
            summary_task = self._aget_session_summary(firestore, session_id)
            
            user_context, summary = await asyncio.gather(user_context_task, summary_task)
            print(f"[Profiling] Session Initialization (Summary + Context) took {time.perf_counter() - step_start:.2f}s")
            
            # 3. Save these as the first messages in the new session's history.
            # We can parallelize these writes too
            step_start = time.perf_counter()
            write_tasks = []
            if user_context:
                write_tasks.append(asyncio.to_thread(firestore.add_system_message, user_context))
            if summary:
                write_tasks.append(asyncio.to_thread(firestore.add_system_message, summary))
            
            if write_tasks:
                await asyncio.gather(*write_tasks)
            print(f"[Profiling] Initial Firestore writes took {time.perf_counter() - step_start:.2f}s")

        # Add the current user query to the history
        step_start = time.perf_counter()
        await asyncio.to_thread(firestore.add_user_message, query)
        print(f"[Profiling] Add user message to Firestore took {time.perf_counter() - step_start:.2f}s")
        
        # Load the complete history for this session, including the newly added context and query
        step_start = time.perf_counter()
        current_session_history = await asyncio.to_thread(firestore.load_messages)

        # Seperate the messages such that the user context and summary is always injected 
        # and only the last `max_messages` are taken from the rest of the messages
        system_messages = [msg for msg in current_session_history if msg.type == 'system']
        other_messages = [msg for msg in current_session_history if msg.type != 'system']
        recent_messages = [{"role": msg.type, "content": msg.content} for msg in system_messages] + \
                        [{"role": msg.type, "content": msg.content} for msg in other_messages[-self.max_messages:]]

        # recent_messages = [{"role": msg.type, "content": msg.content} for msg in current_session_history[-self.max_messages:]]
        print(f"[Profiling] Reloading history took {time.perf_counter() - step_start:.2f}s")
        
        # Set status: Agent Thinking
        await asyncio.to_thread(firestore.set_status, "agent_thinking")

        # Extract text response
        response_content = None
        for attempt in range(max_retries):
            try:
                step_start = time.perf_counter()
                result = await self.agent.ainvoke({"messages": recent_messages})
                print(f"[Profiling] LLM Agent (attempt {attempt+1}) took {time.perf_counter() - step_start:.2f}s")
                
                if result.get("finish_reason") == "MALFORMED_FUNCTION_CALL":
                    raise RuntimeError("Tool call failed due to malformed arguments")
                
                response_content = self._extract_text_content(result["messages"][-1].content)
                
                if response_content:
                    break

                raise EmptyLLMResponseError()
            
            except EmptyLLMResponseError as e:
                if attempt == max_retries-1:
                    response_content = {"message": "I could not generate a response. Please try again", "ui_actions": []}
        
        # Set status: Finishing
        await asyncio.to_thread(firestore.set_status, "finishing")

        # Store as plain text in Firestore if response is non empty to avoid InvalidArg error
        if response_content:
            # 1. Decide what to store in Firestore history
            if isinstance(response_content, dict):
                # Store just the text message so the AI can read its history later
                db_text = response_content.get("message", "Data response sent.")
                # Non-blocking firestore write
                asyncio.create_task(asyncio.to_thread(firestore.add_ai_message, db_text))
            else:
                # Fallback if it somehow returned a string
                asyncio.create_task(asyncio.to_thread(firestore.add_ai_message, str(response_content)))
        else:
            print("Response content is empty, skipping Firestore write")
        
        print(f"[Profiling] TOTAL ainvoke_res took {time.perf_counter() - total_start:.2f}s")
        return response_content

    def _get_session_summary(self, firestore: FireStoreChat, session_id: str = None) -> str:
        """ Retrieve all previous sessions for this user and summarise each into a single output"""
        try:
            data = firestore.load_all_messages(current_session_id=session_id)
            if not data:
                return ""
            
            out = self.llm.invoke(f"You are a helpful assistant that summarises conversations briefly, incorporating all important information from the conversation. Focus on key topics discussed, important user preferences, and any ongoing context. Summarise the following: {data}")
            if(hasattr(out, 'content')):
                summary = out.content
            else:
                summary = str(out)

            return summary
        except Exception as e:
            print(f"Error getting session summary: {e}")
            return ""
    
    def invoke_res(self, query: str, user_id: str = None, session_id: str = None):
        max_retries = 2
        session_id = self._get_daily_session_id(user_id)

        # Initialize Firestore for the current user and session
        firestore = self._init_FireStore(user_id, session_id)
        
        # Check if this is the first message in the session to inject context
        current_session_history = firestore.load_messages()
        is_new_session = len(current_session_history) == 0

        if is_new_session:
            print("New session detected. Injecting user context and session summary.")
            # 1. Get the long-term user profile context.
            user_context = firestore.get_user_context()
            
            # 2. Generate a summary of all *previous* conversations.
            summary = self._get_session_summary(firestore, session_id)
            
            # 3. Save these as the first messages in the new session's history.
            if user_context:
                firestore.add_system_message(user_context)
            if summary:
                firestore.add_system_message(summary)

        # Add the current user query to the history
        firestore.add_user_message(query)
        
        # Load the complete history for this session, including the newly added context and query
        current_session_history = firestore.load_messages()
        recent_messages = [{"role": msg.type, "content": msg.content} for msg in current_session_history[-self.max_messages:]]
        
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