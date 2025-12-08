from google import genai
from google.genai import types

project_id = 'dash-beta-e61d0'
location = 'europe-west1'

class classifier():
    def __init__(self):
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location
        )
        
        self.model = 'gemini-2.5-flash'

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
        return response.text
