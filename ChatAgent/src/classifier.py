from google import genai
import time

from tools import ToolList, search_query
from agent import agent

project_id = 'dash-beta-e61d0'
location = 'europe-west1'

class classifier():
    def __init__(self, system_instruction_gen, system_instruction_plan, system_instruction_act):
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location
        )
        
        self.model = 'gemini-2.5-pro'
        self.classifier_model = 'gemini-2.5-flash'

        self.tool = ToolList()
        self.generalist = agent(self.model, system_instruction_gen, self.tool.get_tools(), search_query)
        self.planning = agent(self.model, system_instruction_plan, self.tool.get_tools(), search_query)
        self.action = agent(self.model, system_instruction_act, self.tool.get_tools(), search_query)

    async def ainvoke(self, query, user_id=None):
        # start = time.perf_counter()
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
            model=self.classifier_model,
            contents=prompt
        )
        # print(f"[Profiling] Classifier ({self.classifier_model}) took {time.perf_counter() - start:.2f}s")

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
