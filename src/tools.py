from langchain_core.tools import tool, Tool
from langchain_google_community import GoogleSearchAPIWrapper
from pydantic import BaseModel, Field
from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import documentai_v1
import os
import dotenv
import requests

dotenv.load_dotenv()

class google_search_input(BaseModel):
    search_query: str = Field(
        description='The natural language query to search on google'
    )

class vertex_search_input(BaseModel):
    search_query: str = Field(
        description='The natural language query to search against the data store'
    ),
    user_id: str = Field(
        description='The id of the user whos documents can be accessed. '
    )

class document_read_input(BaseModel):
    document_url: str = Field(
        description='The url of the document that must be read'
    )

class ToolList:
    def __init__(self):
        self.search_wrapper = GoogleSearchAPIWrapper()
        self.project_id = os.getenv("GOOGLE_PROJECT_ID")
        self.location = os.getenv("GOOGLE_LOCATION")
        self.location_vertexAI = "eu"
        self.engine_id = os.getenv("VERTEX_ENGINE_ID")
        self.document_ai_id = os.getenv("DOCUMENT_AI_ID")

        # Initialise document AI client
        # Set api endpoint to eu
        opts = ClientOptions(api_endpoint=f"{self.location_vertexAI}-documentai.googleapis.com")
        self.docai_client = documentai_v1.DocumentProcessorServiceClient(client_options=opts)
        # Processor reference
        self.processor_name = self.docai_client.processor_path(
            self.project_id, 
            self.location_vertexAI,
            self.document_ai_id
        )

    def _logged_search(
        self,
        query
    ):
        print(f"Google called with query: {query}")
        result = self.search_wrapper.run(query)
        print(f"Search result: {result[:200]}...")
        return result
    
    def _document_read(
        self,
        document_url
    ):
        """
        Extracts full textual content from a PDF document using Google Document AI.

        This method uses a pre-configured Document AI processor to read and
        OCR a PDF file (such as invoices, utility bills, or reports) and returns
        the extracted raw text. It is designed for structured and unstructured
        sustainability-related documents where precise text extraction is required
        prior to downstream analysis (e.g. energy consumption parsing).

        The function assumes:
        - The document is accessible locally (downloaded beforehand).
        - The document is a PDF (`application/pdf`).

        Parameters
        ----------
        document_url : str
            URL or file path to the PDF document

        Returns
        -------
        str
            The full extracted text content of the document as a single string,
            preserving reading order as returned by Document AI.

        Raises
        ------
        google.api_core.exceptions.GoogleAPICallError
            If the Document AI API request fails.
        google.api_core.exceptions.NotFound
            If the specified processor does not exist or is inaccessible.
        IOError
            If the document file cannot be read from the provided path.
        """

        if document_url.startswith("http://") or document_url.startswith("https://"):
            response = requests.get(document_url, timeout=30)
            response.raise_for_status()
            image_content = response.content
        else:
            # Read from local file
            if not os.path.exists(document_url):
                raise FileNotFoundError(f"File not found: {document_url}")
            
            with open(document_url, "rb") as image:
                image_content = image.read()

        raw_doc = documentai_v1.RawDocument(
            content=image_content,
            mime_type="application/pdf"
        )

        # Send request to process document
        request = documentai_v1.ProcessRequest(name=self.processor_name, raw_document=raw_doc)
        result = self.docai_client.process_document(request=request)
        document = result.document

        return document.text
    
    # @tool(args_schema=search_input)
    def _search_db(
        self,
        search_query: str = "",
        user_id: str = None
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
        user_id : str
            The user ID to filter documents by. Only documents belonging to this
            user will be returned.

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
        print("Using vertex")
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
        content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True
            ),
            # reference: https://cloud.google.com/generative-ai-app-builder/docs/get-search-summaries
            summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                summary_result_count=10,
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
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=3,
                max_extractive_segment_count=3,
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

        # Filter for user_id
        if user_id:
            request.filter = f'user_id: ANY("{user_id}")'

        page_result = client.search(request)

        # summary = page_result.summary.summary_text if page_result.summary else ""

        # documents_found = []
        # for result in page_result:
        #     doc_info = {}
            
        #     try:
        #         # Access struct_data as a dictionary
        #         struct_data = dict(result.document.struct_data)
                
        #         # Check if there's a nested 'structData' field
        #         if 'structData' in struct_data:
        #             # This is structured data store format
        #             nested_struct = struct_data['structData']
        #             doc_info['document_type'] = nested_struct.get('document_type', 'Unknown')
        #             doc_info['company_name'] = nested_struct.get('company_name', 'Unknown')
        #             doc_info['uploaded_time'] = nested_struct.get('uploaded_time', 'Unknown')
        #             doc_info['region'] = nested_struct.get('region', 'Unknown')
        #             doc_info['industry'] = nested_struct.get('industry', 'Unknown')
                    
        #             # Extract consumption data if available
        #             if 'data' in nested_struct and nested_struct['data']:
        #                 data_fields = nested_struct['data']
        #                 doc_info['consumption_kwh'] = data_fields.get('consumption_kwh')
        #                 doc_info['billing_period_start'] = data_fields.get('billing_period_start')
        #                 doc_info['billing_period_end'] = data_fields.get('billing_period_end')
        #         else:
        #             # This is unstructured data store format (metadata at top level)
        #             doc_info['document_type'] = struct_data.get('document_type', 'Unknown')
        #             doc_info['company_name'] = struct_data.get('company_name', 'Unknown')
        #             doc_info['uploaded_time'] = struct_data.get('uploaded_time', 'Unknown')
        #             doc_info['region'] = struct_data.get('region', 'Unknown')
        #             doc_info['industry'] = struct_data.get('industry', 'Unknown')
                
        #         # Get content text
        #         if 'content' in struct_data:
        #             content = struct_data['content']
        #             if isinstance(content, dict):
        #                 doc_info['content_text'] = content.get('text', '')
                
        #         # Extract from derived_struct_data
        #         if hasattr(result.document, 'derived_struct_data'):
        #             derived_data = dict(result.document.derived_struct_data)
        #             doc_info['title'] = derived_data.get('title', '')
        #             doc_info['link'] = derived_data.get('link', '')
                    
        #             # Extract snippets
        #             if 'snippets' in derived_data:
        #                 snippets = derived_data['snippets']
        #                 if snippets and len(snippets) > 0:
        #                     snippet_data = snippets[0]
        #                     if isinstance(snippet_data, dict):
        #                         doc_info['snippet'] = snippet_data.get('snippet', '')
                
        #         if doc_info:
        #             documents_found.append(doc_info)
                    
        #     except Exception as e:
        #         print(f"Error extracting document info: {e}")
        #         continue
        
        # # Format the response
        # if not documents_found:
        #     return "SUMMARY:\nNo documents found matching your query."
        
        # # Create a structured response
        # response = f"Found {len(documents_found)} document(s):\n\n"
        
        # for i, doc in enumerate(documents_found[:10], 1):
        #     response += f"{i}. "
            
        #     # Add title if available
        #     if doc.get('title'):
        #         response += f"**{doc['title']}**\n"
        #     else:
        #         response += f"**Document {i}**\n"
            
        #     # Add document type and company
        #     metadata_parts = []
        #     if doc.get('document_type'):
        #         metadata_parts.append(f"Type: {doc['document_type']}")
        #     if doc.get('company_name'):
        #         metadata_parts.append(f"Company: {doc['company_name']}")
        #     if metadata_parts:
        #         response += f"   {' | '.join(metadata_parts)}\n"
            
        #     # Add consumption data if available (structured data)
        #     if doc.get('consumption_kwh'):
        #         response += f"   **Consumption:** {doc['consumption_kwh']} kWh\n"
        #     if doc.get('billing_period_start'):
        #         end = doc.get('billing_period_end', 'N/A')
        #         response += f"   **Billing Period:** {doc['billing_period_start']} to {end}\n"
            
        #     # Add content text (for structured data with parsed info)
        #     if doc.get('content_text'):
        #         # Clean up the content text
        #         content = doc['content_text'].replace('Document type:', '\n   Type:')
        #         response += f"   {content}\n"
            
        #     # Add snippet (for unstructured data)
        #     elif doc.get('snippet'):
        #         response += f"   {doc['snippet']}\n"
            
        #     # Add upload time if no other details
        #     if doc.get('uploaded_time') and not doc.get('content_text') and not doc.get('snippet'):
        #         response += f"   Uploaded: {doc['uploaded_time']}\n"
            
        #     response += "\n"

        # print(response)
        # return response
        
        # Include the citations/results for context
        # citations = "\n".join([c.uri for c in page_result.summary.CitationMetadata.citations]) if page_result.summary and page_result.summary.CitationMetadata else ""

        # Handle the response
        # for response in page_result:
        #     print(response)
        
        # print(page_result._response)
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
    
    def _get_value(v):
        if v is None:
            return None
        if isinstance(v, str):
            return v
        if hasattr(v, "string_value"):
            return v.string_value
        if hasattr(v, "number_value"):
            return v.number_value
        return None

    def _search_db2(self, search_query: str, user_id: str | None = None):
        """
        Retrieve any document uploaded by the user that matches the query.
        Always returns documents if they exist.
        Optionally includes a lightweight LLM-generated description.
        """

        # -------- Client setup --------
        client_options = (
            ClientOptions(api_endpoint=f"{self.location_vertexAI}-discoveryengine.googleapis.com")
            if self.location_vertexAI != "global"
            else None
        )

        client = discoveryengine.SearchServiceClient(client_options=client_options)

        serving_config = (
            f"projects/{self.project_id}/locations/{self.location_vertexAI}"
            f"/collections/default_collection/engines/{self.engine_id}"
            f"/servingConfigs/default_config"
        )

        # -------- Content search config --------
        content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True
            ),
            # Keep summaries lightweight and non-authoritative
            summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                summary_result_count=5,
                include_citations=True,
                ignore_adversarial_query=True,
                ignore_non_summary_seeking_query=True, 
                model_prompt_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelPromptSpec(
                    preamble=(
                        "You are assisting in document retrieval. "
                        "Briefly describe what kinds of documents were found, "
                        "without inferring or inventing missing information. "
                        "If unsure, say what is visible in metadata only."
                    )
                ),
                model_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelSpec(
                    version="stable"
                ),
            ),
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=2,
                max_extractive_segment_count=2,
            ),
        )

        # -------- Search request --------
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=search_query,
            page_size=10,
            content_search_spec=content_search_spec,
            spell_correction_spec=discoveryengine.SearchRequest.SpellCorrectionSpec(
                mode=discoveryengine.SearchRequest.SpellCorrectionSpec.Mode.AUTO
            ),
        )

        # -------- User isolation filter --------
        if user_id:
            request.filter = f'user_id: ANY("{user_id}")'

        # -------- Execute search --------
        pager = client.search(request)

        # ---- Read summary from first page ----
        first_page = next(pager.pages, None)
        
        if not first_page:
            return {
                "summary": "No documents matched your query",
                "documents": []
            }

        # --------- Summary --------------
        summary_text = ""
        if first_page.summary:
            summary_text = first_page.summary.summary_text or ""

        print("Sum", summary_text)

        # -------- Collect documents --------
        documents = []

        for result in first_page.results:
            doc = result.document

            derived = doc.derived_struct_data or {}
            struct = doc.struct_data or {}

            documents.append({
                "document_id": doc.id,
                "title": self._get_value(derived.get("title")),
                "entity_type": self._get_value(derived.get("entity_type")),
                "snippet": (
                    self._get_value(
                        derived.get("snippets", {})
                        .get("list_value", {})
                        .get("values", [{}])[0]
                        .get("struct_value", {})
                        .get("fields", {})
                        .get("snippet")
                    )
                ),
                "link": self._get_value(derived.get("link")),
                "metadata": {
                    k: self._get_value(v)
                    for k, v in (struct.get("fields") or {}).items()
                },
            })  

        print("Docs", documents)

        # -------- Final response --------
        if not documents:
            return {
                "summary": "No documents matched your query.",
                "documents": []
            }

        return {
            "summary": summary_text or "Matching documents were found.",
            "documents": documents
        }


    def get_tools(self) -> list[Tool]:
        google_search_tool = Tool(
            name="google_search",  # The name the LLM calls
            description="Search Google for current events and real-time facts.",
            args_schema=google_search_input,
            func=self.search_wrapper.run,
        )

        vertex_doc_search_tool = Tool(
            name="vertex_doc_search", 
            description="""Search user's internal sustainability documents (electricity bills, invoices, 
            emissions reports, consumption data, etc.) using Vertex AI Search. 
            
            Use this tool for ANY query about:
            - Energy consumption or electricity usage
            - Billing information or invoices
            - Emissions or carbon data
            - Historical sustainability metrics
            - Company-specific environmental data
            
            Input: A natural language search query (e.g., 'electricity bill March 2024' or 'energy consumption last year')
            Output: Summary of relevant information from the user's documents.""", 
            args_schema=vertex_search_input,
            func=self._search_db2, 
        )
        
        document_read_tool = Tool(
            name="document_read",
            description="Extract text from a PDF using Document AI.",
            args_schema=document_read_input,
            func=self._document_read, 
        )

        tools_list = [google_search_tool, vertex_doc_search_tool, document_read_tool]

        return tools_list