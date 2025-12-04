from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from langchain_google_vertexai import ChatVertexAI
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest

class agent:
    def __init__(self, model_name: str,  system_prompt: str, tool_set, search_input):
        self.basic_model = model_name
        self.advanced_model = "gemini-2.5-pro"

        self.tool_list = tool_set
        self.system_prompt = system_prompt
        self.search_input = search_input

        # Safety - content filter configuration
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_LOW_AND_ABOVE,
        }

        self.model_kwargs = {
            # Temperature - degree of randomness
            "temperature": 1.0, 
            # Max output tokens - limit max text output from one promp
            "max_output_tokens": 1000,
            # Top p - select x tokens till sum of probability = top_p
            "top_p": 0.95,
            # Top k - next token selected among top-k 
            "top_k": None,
            "safety_settings": self.safety_settings
        }

        self.llm = self._create_llm()
        self.agent = self._create_agent(self.llm)

    # Enable switching to pro model 
    @wrap_model_call
    def _model_selection(self, request: ModelRequest, handler, tools_list):
        """Choose model based on conversation complexity"""
        message_count = len(request.state["messages"])

        # Choose larger model for longer conversations 
        if message_count > 10:
            print(f"Selecting Advanced Model ({self.advanced_model})")
            model_name = self.advanced_model
        else:
            print(f"Selecting Basic Model ({self.basic_model})")
            model_name = self.basic_model
        
        # Bind model to google search
        model = ChatVertexAI(
            model_name=model_name,
            temperature=self.model_kwargs.get('temperature'),
            max_tokens=self.model_kwargs.get('max_output_tokens'),
            top_p=self.model_kwargs.get('top_p'),
            top_k=self.model_kwargs.get('top_k'),
            # safety_settings=model_kwargs.get('safety_settings'),
        ).bind_tools(self.tool_list)

        return handler(request.override(model=model))

    def _create_llm(self):
        llm = ChatVertexAI(
            model_name=self.basic_model,
            temperature=self.model_kwargs.get('temperature'),
            max_tokens=self.model_kwargs.get('max_output_tokens'),
            top_p=self.model_kwargs.get('top_p'),
            top_k=self.model_kwargs.get('top_k'),
            # safety_settings=model_kwargs.get('safety_settings'),
        ).bind_tools(self.tool_list)

        return llm

    def _create_agent(self, llm):
        # Create agent
        agent = create_agent(
            llm,
            tools=self.tool_list,
            system_prompt=self.system_prompt,
            context_schema=self.search_input,
            # middleware=[self._model_selection]
        )

        return agent

    def get_agent_response(self, agent, query):
        result = agent.invoke(
            {"messages": [{"role": "user", "content": query}]}
        )

        return result["messages"][-1].content