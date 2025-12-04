from agent import agent
from tools import ToolList, search_input
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')

system_instruction = (
    "You are a helpful assistant. For ANY question about events, prizes, awards, "
    "current information, or anything that may have occurred recently, you MUST use "
    "the 'google_search' tool FIRST before answering. Never answer questions about "
    "recent events from your training data alone. If you're unsure whether something "
    "is recent, use google_search to verify. Use the 'vertex_doc_search' tool for questions "
    "about internal documents, like consumption data. Start every answer with 'Doh!' "
)

model = "gemini-2.5-flash"

tool = ToolList()
ag = agent(model, system_instruction, tool.get_tools(), search_input)

# Test for google tool
result1 = ag.agent.invoke({"messages": [{"role": "user", "content": "Who won the nobel prize in physics in 2025?"}]})
# print(f"Google Result: {result1}")
print(f"Google Result: {result1['messages'][-1].content}")

# Test for vertex AI search
result2 = ag.agent.invoke({"messages": [{"role": "user", "content": "Provide the consumption from the electricity bill document"}]})
print(result2["messages"][-1].content)