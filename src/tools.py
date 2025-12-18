from langchain_core.tools import tool, Tool
from langchain_google_community import GoogleSearchAPIWrapper
from pydantic import BaseModel, Field
from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine
import os
import dotenv

dotenv.load_dotenv()

class search_input(BaseModel):
    search_query: str = Field(
        description='The natural language query to search against the data stores'
    )

class ToolList:
    def __init__(self):
        self.search_wrapper = GoogleSearchAPIWrapper()
        self.project_id = os.getenv("GOOGLE_PROJECT_ID")
        self.location = os.getenv("GOOGLE_LOCATION")
        self.location_vertexAI = "eu"
        self.engine_id = os.getenv("VERTEX_ENGINE_ID")

    def _logged_search(self, query):
        print(f"Google called with query: {query}")
        result = self.search_wrapper.run(query)
        print(f"Search result: {result[:200]}...")
        return result
    
    # @tool(args_schema=search_input)
    def _search_sample(
        self,
        search_query: str = ""
    ) -> str:
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

        Returns
        -------
        str:
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
            ClientOptions(api_endpoint=f"{self.location_vertexAI}-discoveryengine.googleapis.com")
            if self.location_vertexAI != "global"
            else None
        )

        # Create a client
        client = discoveryengine.SearchServiceClient(client_options=client_options)

        # The full resource name of the search app serving config
        serving_config = f"projects/{self.project_id}/locations/{self.location_vertexAI}/collections/default_collection/engines/{self.engine_id}/servingConfigs/default_config"

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
        
        # Include the citations/results for context
        # citations = "\n".join([c.uri for c in page_result.summary.CitationMetadata.citations]) if page_result.summary and page_result.summary.CitationMetadata else ""

        # Handle the response
        # for response in page_result:
        #     print(response)
        
        # Return the summary text for the LLM to use
        # return f"Result from internal documents: {page_result._response}"
        summary = page_result.summary.summary_text if page_result.summary else ""

        # snippets = []
        # for r in page_result:
        #     if r.document.derived_struct_data.get("snippets"):
        #         snippets.append(r.document.derived_struct_data["snippets"][0]["snippet"])

        return f"""
        SUMMARY:
        {summary}"""

        # SNIPPETS:\n
        # {snippets}
        # """

    def get_tools(self) -> list[Tool]:
        google_search_tool = Tool(
            name="google_search",  # The name the LLM calls
            description="Search Google for current events and real-time facts.",
            func=self.search_wrapper.run,
        )

        tools_list = [google_search_tool, self._search_sample]

        return tools_list