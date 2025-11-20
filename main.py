from google import genai
from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from vertexai import agent_engines
from vertexai.generative_models import grounding, Tool

project_id = 'dash-beta-e61d0'
location = 'europe-west1'

client_gemini = genai.Client(
    vertexai=True, project=project_id, location=location
)

model = "gemini-2.5-flash"

# Safety - content filter configuration
safety_settings = {
    HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
}

model_kwargs = {
    # Temperature - degree of randomness
    "temperature": 1.0, 
    # Max output tokens - limit max text output from one promp
    "max_output_tokens": 1000,
    # Top p - select x tokens till sum of probability = top_p
    "top_p": 0.95,
    # Top k - next token selected among top-k 
    "top_k": None,
    "safety_settings": safety_settings
}

grounded_search_tool = Tool.from_google_search_retrieval(
    grounding.GoogleSearchRetrieval()
)

agent = agent_engines.LangchainAgent(
    model=model,
    model_kwargs=model_kwargs,
    tools=[grounded_search_tool]
)

response = agent.query(input="When is the next total solar eclipse in UK?")
print(response)




