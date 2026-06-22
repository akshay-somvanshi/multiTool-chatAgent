# from agent import agent
from chat_agent.classifier import classifier
# from tools import ToolList, search_input
from google import genai

from pydantic import BaseModel, Field
from typing import List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import os
import json
from dotenv import load_dotenv

location = 'europe-west1'

load_dotenv()

GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GOOGLE_CSE_ID = os.getenv('GOOGLE_CSE_ID')
GOOGLE_PROJECT_ID = os.getenv('GOOGLE_PROJECT_ID')

def load_prompt(file_path: str) -> str:
    with open(file_path, 'r') as f:
        return f.read()

def load_and_format_prompt(template_path: str, **kwargs) -> str:
    template = load_prompt(template_path)
    return template.format(**kwargs)

with open("chat_agent/data/planning_questions.json") as qs:
    plan_questions = json.load(qs)

dash_identity = load_prompt("chat_agent/prompts/identity.md")
system_instruction_gen = load_and_format_prompt("chat_agent/prompts/system_general.md", dash_identity=dash_identity)
system_instruction_plan = load_and_format_prompt("chat_agent/prompts/system_planning.md", dash_identity=dash_identity, plan_questions=json.dumps(plan_questions, indent=2))
system_instruction_act = load_and_format_prompt("chat_agent/prompts/system_action.md", dash_identity=dash_identity)

# Text-only channel prompts (e.g. WhatsApp): the same web prompt with a high-priority
# override appended that suppresses all UI rendering blocks and forces plain text.
# Loaded raw (no .format) so its braces/backticks are preserved verbatim.
channel_text_override = load_prompt("chat_agent/prompts/channel_text_override.md")
system_instruction_gen_text = system_instruction_gen + "\n\n" + channel_text_override
system_instruction_plan_text = system_instruction_plan + "\n\n" + channel_text_override
system_instruction_act_text = system_instruction_act + "\n\n" + channel_text_override

model = "gemini-3.5-flash"

# Initialise the classifier
classifier = classifier(
    system_instruction_gen=system_instruction_gen,
    system_instruction_plan=system_instruction_plan,
    system_instruction_act=system_instruction_act,
    system_instruction_gen_text=system_instruction_gen_text,
    system_instruction_plan_text=system_instruction_plan_text,
    system_instruction_act_text=system_instruction_act_text
)

# Initialise the front end chatbot
client = genai.Client(
    vertexai=True,
    project=GOOGLE_PROJECT_ID,
    location=location
)

# client.models.generate_content(
#     model=model,
#     contents=prompt
# )

# Test for google tool
# result1 = generalist.agent.invoke({"messages": [{"role": "user", "content": "Google search who won the nobel prize in physics in 2025?"}]})
# print(f"Google Result: {result1}")
# print(f"Google Result: {result1['messages'][-1].content}")

# Test for vertex AI search
# result2 = classifier.invoke("Tell me about my consumption from electricity bill")
# print(f'Vertex AI search: {result2}')

# Test classifier
# query = "Can you extract the electricity information from this: https://storage.googleapis.com/dash-beta-e61d0.firebasestorage.app/users/CORZZX0MxTQtGyAD7PSCI1HLp3y2/uploads/Energia%20-%20luglio%202024_ft%2020824956.pdf"
# response = classifier.invoke(query, "QLRmwioROPcNz3t80XzUhn9icey1")
# print(response)

# API setup
app = FastAPI(title="Chatbot", description="Dash agent", version="0.1")

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatIn(BaseModel):
    message: str = Field(description="User message")
    user_id: str = Field(description="Unique user identifier")
    text_only: bool = Field(
        default=False,
        description="Plain-text channel (e.g. WhatsApp): suppress all UI rendering blocks."
    )

class UIAction(BaseModel):
    type: str
    payload: Any  # dict? 

class ChatResponseContent(BaseModel):
    message: str
    ui_actions: List[UIAction]

class ChatOut(BaseModel):
    response: ChatResponseContent

# Default root endpoint as health check
@app.get("/", status_code=200)
async def root():
    return {"message": "The chatbot seems to be up and running!"}

@app.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn):
    try:
        if body.text_only:
            print(f"[TextOnly] /chat request | user_id={body.user_id} | msg_len={len(body.message)}", flush=True)
        response = await classifier.ainvoke(body.message, body.user_id, text_only=body.text_only)
        return ChatOut(response=response)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

@app.post("/stream")
async def chat_stream(body: ChatIn):
    try:
        return StreamingResponse(
            classifier.astream_res(body.message, body.user_id),
            media_type="text/event-stream"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")