from google import genai
import time

from chat_agent.tools import ToolList, search_query
from chat_agent.agent import agent
from chat_agent.firestore import FireStoreChat
from datetime import datetime

project_id = 'dash-beta-e61d0'
location = 'europe-west1'
location_global = 'global'

class classifier():
    def __init__(self, system_instruction_gen, system_instruction_plan, system_instruction_act):
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location_global
        )
        
        self.model = 'gemini-3-flash-preview'

        self.tool = ToolList()
        self.generalist = agent(self.model, system_instruction_gen, self.tool.get_tools(), search_query)
        self.planning = agent(self.model, system_instruction_plan, self.tool.get_tools(), search_query)
        self.action = agent(self.model, system_instruction_act, self.tool.get_tools(), search_query)

    def _get_daily_session_id(self, user_id: str) -> str:
        """Create one session per day"""
        today = datetime.now().strftime('%Y%m%d')
        return f"{today}"

    async def astream_res(self, query, user_id=None):
        start = time.perf_counter()
        
        # Set status
        if user_id:
            session_id = self._get_daily_session_id(user_id)
            firestore = FireStoreChat(user_id, session_id)
            firestore.set_status("classifier")

        prompt = f"""
        You are a classifier that decides which operational mode to use.

        Modes:
        1. GENERALIST — basic information, basic research, definitions, general knowledge questions.
        2. PLANNING — user wants structured sustainability planning, assessments, or a future roadmap.
        3. ACTION — user wants implementation steps, changing action items, timelines, operational detail.

        User query: "{query}"

        Respond ONLY with one of:
        GENERALIST
        PLANNING
        ACTION
        """
        # Using .aio for true async call with google-genai SDK
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt
        )
        print(f"[Profiling] Classifier ({self.model}) took {time.perf_counter() - start:.2f}s")

        if response.text.strip() == "GENERALIST":
            async for chunk in self.generalist.astream_res(query, user_id):
                yield chunk
        elif response.text.strip() == "PLANNING":
            async for chunk in self.planning.astream_res(query, user_id):
                yield chunk
        else:
            async for chunk in self.action.astream_res(query, user_id):
                yield chunk

    async def ainvoke(self, query, user_id=None):
        start = time.perf_counter()
        
        # Set status
        if user_id:
            session_id = self._get_daily_session_id(user_id)
            firestore = FireStoreChat(user_id, session_id)
            firestore.set_status("classifier")

        prompt = f"""
        You are a classifier that decides which operational mode to use.

        Modes:
        1. GENERALIST — basic information, basic research, definitions, general knowledge questions.
        2. PLANNING — user wants structured sustainability planning, assessments, or a future roadmap.
        3. ACTION — user wants implementation steps, changing action items, timelines, operational detail.

        User query: "{query}"

        Respond ONLY with one of:
        GENERALIST
        PLANNING
        ACTION
        """
        # Using .aio for true async call with google-genai SDK
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt
        )
        print(f"[Profiling] Classifier ({self.model}) took {time.perf_counter() - start:.2f}s")

        if response.text.strip() == "GENERALIST":
            return await self.generalist.ainvoke_res(query, user_id)
        elif response.text.strip() == "PLANNING":
            return await self.planning.ainvoke_res(query, user_id)
        else:
            return await self.action.ainvoke_res(query, user_id)

    def invoke(self,query,user_id=None):
        # Sync version for compatibility if needed
        prompt = f"""
        You are a classifier that decides which operational mode to use.

        Modes:
        1. GENERALIST — basic information, basic research, definitions, general knowledge questions.
        2. PLANNING — user wants structured sustainability planning, assessments, or a future roadmap.
        3. ACTION — user wants implementation steps, changing action items, timelines, operational detail.

        User query: "{query}"

        Respond ONLY with one of:
        GENERALIST
        PLANNING
        ACTION
        """
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt
        )

        if response.text.strip() == "GENERALIST":
            return(self.generalist.invoke_res(query, user_id))
        elif response.text.strip() == "PLANNING":
            return(self.planning.invoke_res(query, user_id))
        else:
            return(self.action.invoke_res(query, user_id))
