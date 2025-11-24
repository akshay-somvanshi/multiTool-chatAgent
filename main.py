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

system_instruction = (
    "You are a helpful assistant. Always use the 'google_search' tool for any questions "
    "related to current events, future events, or any information that changes over time "
    "such as news, weather, or real-time facts. Only answer from your internal knowledge "
    "if the information is general or timeless (e.g., historical facts). Start every answer with 'Doh!' "
)

model_kwargs = {
    # Temperature - degree of randomness
    "temperature": 1.0, 
    # Max output tokens - limit max text output from one promp
    "max_output_tokens": 1000,
    # Top p - select x tokens till sum of probability = top_p
    "top_p": 0.95,
    # Top k - next token selected among top-k 
    "top_k": None,
    "safety_settings": safety_settings,
    "system_instruction": system_instruction,
}

@tool
def search_web(query: str):
    """Search the web"""
    return f"Search result placeholder for: {query}"

tools_list = []

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
    
    # Bind model to google search
    model = ChatVertexAI(
        model_name=model_name,
        temperature=model_kwargs.get('temperature'),
        max_tokens=model_kwargs.get('max_output_tokens'),
        top_p=model_kwargs.get('top_p'),
        top_k=model_kwargs.get('top_k'),
        # safety_settings=model_kwargs.get('safety_settings'),
    ).bind_tools([{"google_search": {}}])

    return handler(request.override(model=model))

# Bind model to google search
llm = ChatVertexAI(
    model_name=basic_model,
    temperature=model_kwargs.get('temperature'),
    max_tokens=model_kwargs.get('max_output_tokens'),
    top_p=model_kwargs.get('top_p'),
    top_k=model_kwargs.get('top_k'),
    # safety_settings=model_kwargs.get('safety_settings'),
).bind_tools([{"google_search": {}}])

# Create agent
agent = create_agent(
    llm,
    tools=tools_list,
    middleware=[model_selection])

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Who won the nobel prize in Physics in 2025?"}]}
)

print(result["messages"][-1].content)
