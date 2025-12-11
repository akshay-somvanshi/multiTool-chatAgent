from google import genai
from tools import ToolList, search_input
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
        
        self.model = 'gemini-2.5-flash'

        self.tool = ToolList()
        self.generalist = agent(self.model, system_instruction_gen, self.tool.get_tools(), search_input)
        self.planning = agent(self.model, system_instruction_plan, self.tool.get_tools(), search_input)
        self.action = agent(self.model, system_instruction_act, self.tool.get_tools(), search_input)

    def invoke(self,query):
        prompt = f"""
        You are a classifier that decides which operational mode to use.

        Modes:
        1. GENERALIST — basic information, basic research, definitions, general knowledge questions.
        2. PLANNING — user wants structured sustainability planning, assessments, or a future roadmap.
        3. ACTION — user wants implementation steps, execution guides, timelines, operational detail.

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

        if response.text == "GENERALIST":
            return(self.generalist.invoke(query))
        elif response.text == "PLANNING":
            return(self.planning.invoke(query))
        else:
            return(self.action.invoke(query))
