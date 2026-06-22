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
    def __init__(self, system_instruction_gen, system_instruction_plan, system_instruction_act,
                 system_instruction_gen_text=None, system_instruction_plan_text=None,
                 system_instruction_act_text=None):
        self.client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location_global
        )

        self.model = 'gemini-3.5-flash'

        self.tool = ToolList()
        # Each agent also gets a text-only system prompt variant (for WhatsApp /
        # other plain-text channels). text_only=True at invoke time selects it.
        self.generalist = agent(self.model, system_instruction_gen, self.tool.get_tools(), search_query,
                                text_system_prompt=system_instruction_gen_text)
        self.planning = agent(self.model, system_instruction_plan, self.tool.get_tools(), search_query,
                              text_system_prompt=system_instruction_plan_text)
        self.action = agent(self.model, system_instruction_act, self.tool.get_tools(), search_query,
                            text_system_prompt=system_instruction_act_text)

    def _get_daily_session_id(self, user_id: str) -> str:
        """Create one session per day"""
        today = datetime.now().strftime('%Y%m%d')
        return f"{today}"

    def _get_classifier_prompt(self, query: str) -> str:
        return f"""You are a routing classifier for Dash, a sustainability AI assistant.

Your only job is to output a single word identifying which mode should handle the user's message. You do not answer the user. You do not explain. You output one word only.

---

## THE THREE MODES

general
The user is asking a question, requesting information, requesting calculations/processing on files, or wants something explained. No changes to the dashboard are being made or planned.
Examples:
- "What is Scope 3 emissions?"
- "Show me our energy usage from last month"
- "Calculate emissions for Company travel - planes trains and automobiles 2023.xlsx"
- "Explain what CDP is"
- "What actions do we currently have?"
- "How does MSCI scoring work?"

planning
The user wants to explore, design, or discuss a sustainability strategy, roadmap, or set of initiatives — but is not committing anything to the dashboard yet.
Examples:
- "Help me build an ESG roadmap for next year"
- "What should we prioritise to improve our CDP score?"
- "I want to plan a net zero strategy"
- "What initiatives would reduce our Scope 2 emissions?"
- "Can you suggest some actions we could take?"

action
The user is explicitly requesting that something be created, changed, or deleted in the dashboard right now.
Examples:
- "Add the LED lighting upgrade to the dashboard"
- "Create an action for our solar panel installation"
- "Remove the fleet electrification action"
- "Update the timeline on the energy audit"

unclear
The message is ambiguous and cannot be confidently routed to any mode.
Examples:
- "Let's get started"
- "Yes" (with no prior context)
- "OK"
- "Can you help me?"

---

## RULES

1. If you are not confident, output: unclear
2. "action" requires explicit intent to write, modify, or delete a specific dashboard item. Never infer it from planning language alone.
   - "I want to reduce emissions" -> planning
   - "Add the emissions action" -> action
3. "general" includes file processing, carbon calculations, knowledge lookups, and questions about existing data.
4. Never output anything except one of these four words (lowercase, single word):
   general | planning | action | unclear

---

## USER QUERY
"{query}"

---

## OUTPUT
One word. No punctuation. No explanation."""

    async def astream_res(self, query, user_id=None):
        start = time.perf_counter()
        
        # Set status
        if user_id:
            session_id = self._get_daily_session_id(user_id)
            firestore = FireStoreChat(user_id, session_id)
            firestore.set_status("classifier")

        prompt = self._get_classifier_prompt(query)
        # Using .aio for true async call with google-genai SDK
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt
        )
        decision = response.text.strip().lower()
        print(f"[Profiling] Classifier ({self.model}) decided '{decision}' in {time.perf_counter() - start:.2f}s", flush=True)

        if decision == "planning":
            async for chunk in self.planning.astream_res(query, user_id):
                yield chunk
        elif decision == "action":
            async for chunk in self.action.astream_res(query, user_id):
                yield chunk
        else: # general or unclear maps to generalist
            async for chunk in self.generalist.astream_res(query, user_id):
                yield chunk

    async def ainvoke(self, query, user_id=None, text_only=False):
        start = time.perf_counter()

        # Set status
        if user_id:
            session_id = self._get_daily_session_id(user_id)
            firestore = FireStoreChat(user_id, session_id)
            firestore.set_status("classifier")

        prompt = self._get_classifier_prompt(query)
        # Using .aio for true async call with google-genai SDK
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt
        )
        decision = response.text.strip().lower()
        print(f"[Profiling] Classifier ({self.model}) decided '{decision}' in {time.perf_counter() - start:.2f}s", flush=True)

        if text_only:
            print(f"[TextOnly] WhatsApp/text channel | routed='{decision}' | user_id={user_id}", flush=True)

        if decision == "planning":
            return await self.planning.ainvoke_res(query, user_id, text_only=text_only)
        elif decision == "action":
            return await self.action.ainvoke_res(query, user_id, text_only=text_only)
        else: # general or unclear maps to generalist
            return await self.generalist.ainvoke_res(query, user_id, text_only=text_only)

    def invoke(self, query, user_id=None):
        prompt = self._get_classifier_prompt(query)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt
        )
        decision = response.text.strip().lower()

        if decision == "planning":
            return self.planning.invoke_res(query, user_id)
        elif decision == "action":
            return self.action.invoke_res(query, user_id)
        else: # general or unclear maps to generalist
            return self.generalist.invoke_res(query, user_id)
