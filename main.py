from google import genai
from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from langchain_google_vertexai import ChatVertexAI
from langchain_google_community import GoogleSearchAPIWrapper
from langchain.agents import create_agent
from langchain_core.tools import tool, Tool
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
import os
from dotenv import load_dotenv

load_dotenv()

project_id = 'dash-beta-e61d0'
location = 'europe-west1'

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

# client_gemini = genai.Client(
#     vertexai=True, project=project_id, location=location
# )

basic_model = "gemini-2.5-flash"
advanced_model = "gemini-2.5-pro"

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

search_wrapper = GoogleSearchAPIWrapper()
google_search_tool = Tool(
    name="google_search",
    description="Search Google for recent results.",
    func=search_wrapper.run,
)

@tool
def search_web(query: str):
    """Search the web"""
    return f"Search result placeholder for: {query}"

tools_list = [google_search_tool]

# Enable switching to pro model 
@wrap_model_call
def model_selection(request: ModelRequest, handler):
    """Choose model based on conversation complexity"""
    message_count = len(request.state["messages"])

    # Choose larger model for longer conversations 
    if message_count > 10:
        print(f"Selecting Advanced Model ({advanced_model})")
        model_name = advanced_model
    else:
        print(f"Selecting Basic Model ({basic_model})")
        model_name = basic_model

    model = ChatVertexAI(
        model_name=model_name,
        temperature=1.0,
        max_output_tokens=1000,
        top_p=0.95,
        safety_settings=safety_settings
    )

    return handler(request.override(model=model))

# Create agent
agent = create_agent(
    basic_model, 
    tools=tools_list,
    middleware=[model_selection])

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Who won the nobel prize in Physics in 2025?"}]}
)

print(result["messages"][-1].content)
