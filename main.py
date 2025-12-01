from langchain_google_vertexai import HarmBlockThreshold, HarmCategory
from langchain_google_vertexai import ChatVertexAI
from langchain_google_community import VertexAISearchRetriever, GoogleSearchAPIWrapper
from langchain.agents import create_agent
from langchain_core.tools import tool, Tool
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from langchain_classic.tools.retriever import create_retriever_tool
import os
from dotenv import load_dotenv
from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine
from pydantic import BaseModel, Field
from typing import Literal

load_dotenv()

project_id = 'dash-beta-e61d0'
location = 'eu'
os.environ['GOOGLE_CLOUD_QUOTA_PROJECT'] = project_id
# The ID of the Search App (Engine) that blends the data stores
engine_id = 'dashbetasearch_1761558631078'

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
    "You are a helpful assistant. For ANY question about events, prizes, awards, "
    "current information, or anything that may have occurred recently, you MUST use "
    "the 'google_search' tool FIRST before answering. Never answer questions about "
    "recent events from your training data alone. If you're unsure whether something "
    "is recent, use google_search to verify. Use the 'vertex_doc_search' tool for questions "
    "about internal documents, like consumption data. Start every answer with 'Doh!' "
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
    "safety_settings": safety_settings
}

search_wrapper = GoogleSearchAPIWrapper()

def logged_search(query):
    print(f"Google called with query: {query}")
    result = search_wrapper.run(query)
    print(f"Search result: {result[:200]}...")
    return result

google_search_tool = Tool(
    name="google_search",  # The name the LLM calls
    description="Search Google for current events and real-time facts.",
    func=search_wrapper.run,
)

search_query = "Get me the electricity bill"

class search_input(BaseModel):
    """Input for searching through Vertex AI search"""
    project_id: str = Field(
        description='The Google Cloud project ID containing the search engine.',
        default=project_id
    )
    location: str = Field(
        description='The multi-region or regional identifier where the search engine is hosted.',
        default=location
    )
    engine_id: str = Field(
        description='The ID of the Vertex AI Search App (Engine) used for blended search.',
        default=engine_id
    )
    search_query: str = Field(
        description='The natural language query to search against the data stores'
    )

@tool(args_schema=search_input)
def search_sample(
    search_query: str,
    project_id: str = project_id,
    location: str = location,
    engine_id: str = engine_id,
) -> discoveryengine.services.search_service.pagers.SearchPager:
    """
    Performs a blended search against a Vertex AI Search (Discovery Engine)
    Search App, leveraging its serving configuration to retrieve and summarize
    search results across multiple data stores.

    This function uses the native Google Cloud SDK to execute a search
    request, including options for snippet retrieval and result summarization.

    Parameters
    ----------
    search_query : str
        The natural language query to search against the data stores (e.g.,
        "What is the energy consumption in March 2024?").
    project_id : str
        The Google Cloud project ID containing the search engine.
    location : str
        The multi-region or regional identifier where the search engine is hosted
        (e.g., 'global', 'us', 'eu').
    engine_id : str
        The ID of the Vertex AI Search App (Engine) used for blended search.

    Returns
    -------
    google.cloud.discoveryengine_v1.services.search_service.pagers.SearchPager
        A pager object containing the search results, including snippets,
        hits, and the final summary (if requested).

    Raises
    ------
    google.api_core.exceptions.InvalidArgument
        If the request contains invalid parameters (e.g., trying to use
        query expansion with multi-datastore search).
    google.api_core.exceptions.NotFound
        If the serving config path based on project_id, location, and engine_id
        is incorrect.
    """
    #  For more information, refer to:
    # https://cloud.google.com/generative-ai-app-builder/docs/locations#specify_a_multi-region_for_your_data_store
    client_options = (
        ClientOptions(api_endpoint=f"{location}-discoveryengine.googleapis.com")
        if location != "global"
        else None
    )

    # Create a client
    client = discoveryengine.SearchServiceClient(client_options=client_options)

    # The full resource name of the search app serving config
    serving_config = f"projects/{project_id}/locations/{location}/collections/default_collection/engines/{engine_id}/servingConfigs/default_config"

    # Optional - only supported for unstructured data: Configuration options for search.
    # Refer to the `ContentSearchSpec` reference for all supported fields:
    # https://cloud.google.com/python/docs/reference/discoveryengine/latest/google.cloud.discoveryengine_v1.types.SearchRequest.ContentSearchSpec
    content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
        # reference: https://cloud.google.com/generative-ai-app-builder/docs/snippets
        snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
            return_snippet=True
        ),
        # reference: https://cloud.google.com/generative-ai-app-builder/docs/get-search-summaries
        summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
            summary_result_count=5,
            include_citations=True,
            ignore_adversarial_query=True,
            ignore_non_summary_seeking_query=True,
            model_prompt_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelPromptSpec(
                preamble="You are an expert analyst. Your task is to extract precise energy consumption data (in kWh) and the corresponding billing period start/end dates from the provided search results. If data is not available, state the closest available consumption data."
            ),
            model_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelSpec(
                version="stable",
            ),
        ),
    )

    # reference: https://cloud.google.com/python/docs/reference/discoveryengine/latest/google.cloud.discoveryengine_v1.types.SearchRequest
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=search_query,
        page_size=10,
        content_search_spec=content_search_spec,
        spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
            mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
        ),
        # Optional: Use fine-tuned model for this request
        # custom_fine_tuning_spec=discoveryengine.CustomFineTuningSpec(
        #     enable_search_adaptor=True
        # ),
    )

    page_result = client.search(request)

    # Extract the summary result, which is what the LLM needs
    search_summary = page_result.summary.summary_text if page_result.summary else "No relevant search results found."
    # print(page_result._response)
    # print(search_summary)
    
    # Include the citations/results for context
    # citations = "\n".join([c.uri for c in page_result.summary.CitationMetadata.citations]) if page_result.summary and page_result.summary.CitationMetadata else ""

    # Handle the response
    # for response in page_result:
    #     print(response)
    
    # Return the summary text for the LLM to use
    return f"Result from internal documents: {page_result._response}\nCitations: "

# Then, we wrap it in a LangChain Tool.
vertex_search_tool = Tool.from_function(
    func=lambda query: search_sample(query, project_id, location, engine_id),
    name="vertex_doc_search",
    description="Searches the internal Vertex AI Search App (blended data stores) for information on consumption, plans, and company documents. Use this for specific internal data.",
    args_schema=search_input
)

tools_list = [google_search_tool, search_sample]

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
    ).bind_tools(tools_list)

    return handler(request.override(model=model))

llm = ChatVertexAI(
    model_name=basic_model,
    temperature=model_kwargs.get('temperature'),
    max_tokens=model_kwargs.get('max_output_tokens'),
    top_p=model_kwargs.get('top_p'),
    top_k=model_kwargs.get('top_k'),
    # safety_settings=model_kwargs.get('safety_settings'),
).bind_tools(tools_list)

# Create agent
agent = create_agent(
    llm,
    tools=tools_list,
    system_prompt=system_instruction,
    context_schema=search_input
    # middleware=[model_selection]
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Provide the consumption from the electricity bill document"}]}
)

print(result["messages"][-1].content)
