# from agent import agent
from chat_agent.classifier import classifier
# from tools import ToolList, search_input
from google import genai

from pydantic import BaseModel, Field
from typing import List, Optional, Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from chat_agent.core.auth import get_user_id

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

model = "gemini-2.5-flash"

# Initialise the classifier
classifier = classifier(
    system_instruction_gen=system_instruction_gen, 
    system_instruction_plan=system_instruction_plan, 
    system_instruction_act=system_instruction_act
)

# Initialise the front end chatbot
client = genai.Client(
    vertexai=True,
    project=GOOGLE_PROJECT_ID,
    location=location
)

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
    user_id: Optional[str] = Field(None, description="Legacy user identifier (ignored if token is present)")

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
async def chat(body: ChatIn, user_id: str = Depends(get_user_id)):
    try:
        response = await classifier.ainvoke(body.message, user_id)
        return ChatOut(response=response)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")