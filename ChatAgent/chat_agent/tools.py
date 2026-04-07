from langchain_core.tools import tool, Tool, StructuredTool
from langchain_google_community import GoogleSearchAPIWrapper
from pydantic import BaseModel, Field
from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import documentai_v1
import os
import dotenv
import requests
import google
from urllib.parse import urlparse, parse_qs
from google.cloud import storage
from datetime import datetime

from chat_agent.api_client import api_client
from chat_agent.core.exceptions import APIError
from chat_agent.core.octopus import OctopusClient
from chat_agent.firestore import FireStoreChat

dotenv.load_dotenv()

class google_search_input(BaseModel):
    search_query: str = Field(
        description='The natural language query to search on google'
    )

class vertex_search_input(BaseModel):
    query: str = Field(
        description='The natural language query to search against the data store'
    ),
    user_id: str = Field(
        description='The id of the user whos documents can be accessed. '
    )

class document_read_input(BaseModel):
    document_url: str = Field(
        description='The url of the document that must be read'
    )

class search_query(BaseModel):
    search_query: str = Field(
        description='The natural language query to process'
    )

class get_api(BaseModel):
    user_id: str = Field(
        description="User id whos actions are fetched from the database"
    )

class EnergyFetchInput(BaseModel):
    user_id: str = Field(description="The user ID")
    days_back: int = Field(default=7, description="Number of days to fetch consumption for (used if period_from is not set)")
    period_from: str | None = Field(default=None, description="Start of the period in ISO format (e.g. 2026-01-01T00:00:00Z)")
    period_to: str | None = Field(default=None, description="End of the period in ISO format (e.g. 2026-02-01T00:00:00Z)")

class AddActionInput(BaseModel):
    user_id: str = Field(description="User ID")
    action_id: str = Field(description="Unique action identifier of type 'action_003'")
    action_name: str = Field(description="Name of the action")
    action_type: str = Field(description="Type of action (e.g., energy_efficiency)")
    action_description: str = Field(description="Detailed description")
    estimated_spend: float = Field(description="Estimated cost in GBP")
    estimated_co2_reduced: float = Field(description="Estimated CO2 reduction in tCO2e/year")
    estimated_revenue_unlocked: float = Field(description="Estimated Revenue potential in GBP")
    plan_id: str = Field(description="Associated plan ID")
    timeline_start: datetime = Field(description="Proposed start date")
    timeline_end: datetime = Field(description="Proposed end date")
    status: str = Field(description="Current status. Default : not_started")

class UpdateActionInput(BaseModel):
    user_id: str = Field(description="User ID")
    action_id: str = Field(description="Unique action identifier of type 'action_003'")
    actual_co2_reduced: float | None = Field(description="Actual CO2 reduced in tCO2e")
    actual_spend: float | None = Field(description="Actual spend in GBP")
    actual_revenue_unlocked: float | None = Field(description="Actual revenue unlocked in GBP")
    day_started: datetime | None = Field(description="Date when action was started")
    day_completed: datetime | None = Field(description="Date when action was completed")

class RemoveActionInput(BaseModel):
    user_id: str = Field(description="User ID")
    action_id: str = Field(description="Unique action identifier of type 'action_003'")

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

        # Initialise discovery engine client
        client_options = (
            ClientOptions(api_endpoint=f"{self.location_vertexAI}-discoveryengine.googleapis.com")
            if self.location_vertexAI != "global"
            else None
        )
        self.discovery_engine_client = discoveryengine.ConversationalSearchServiceClient(client_options=client_options) 

    def _logged_search(
        self,
        query
    ):
        print(f"Google called with query: {query}")
        result = self.search_wrapper.run(query)
        print(f"Search result: {result[:200]}...")
        return result

    def _download_from_gcs(self, url):
        """
        Download a file from Google Cloud Storage using the standard storage client.
        
        Supports multiple URL formats:
        - Authenticated Console URLs (storage.cloud.google.com/bucket/blob)
        - Public API URLs (storage.googleapis.com/bucket/blob)
        - Subdomain API URLs (bucket.storage.googleapis.com/blob)
        - Firebase Storage URLs (bucket.firebasestorage.app/blob)
        - Native gs:// URI format (gs://bucket/blob)

        If the file has a .txt or .csv extension, it is returned as a UTF-8 string. 
        Otherwise, it is returned as raw bytes.

        Args:
            url (str): The GCS URL or gs:// URI to download.

        Returns:
            Union[str, bytes]: File content as text (for .txt/.csv) or bytes (other formats).
        """
        try:
            # Handle native gs:// format
            if url.startswith("gs://"):
                parts = url[5:].split('/', 1)
                bucket_name = parts[0]
                blob_path = parts[1] if len(parts) > 1 else ""
            else:
                parsed = urlparse(url)
                netloc = parsed.netloc
                path = parsed.path.lstrip('/')
                
                # Extract bucket and blob based on host
                if 'storage.cloud.google.com' in netloc:
                    bucket_name, blob_path = path.split('/', 1)
                elif 'storage.googleapis.com' in netloc:
                    if netloc == 'storage.googleapis.com':
                        bucket_name, blob_path = path.split('/', 1)
                    else:
                        bucket_name = netloc.split('.')[0]
                        blob_path = path
                elif 'firebasestorage.app' in netloc:
                    bucket_name = netloc.split('.')[0]
                    blob_path = path
                else:
                    raise ValueError(f"Unsupported GCS URL format: {url}")

            print(f"Downloading from GCS: bucket={bucket_name}, path={blob_path}", flush=True)
            
            storage_client = storage.Client(project=self.project_id)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            # Simple text vs bytes logic
            if blob_path.lower().endswith('.txt') or blob_path.lower().endswith('.csv'):
                print(f"Downloading {blob_path} as text", flush=True)
                content = blob.download_as_text()
            else:
                content = blob.download_as_bytes()
            
            return content
            
        except Exception as e:
            print(f"GCS download failed: {e}. Falling back to HTTP.", flush=True)
            return self._download_from_http(url)

    def _download_from_http(self, url):
        """Download file via HTTP."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; DocumentAI/1.0)'
        }
        
        response = requests.get(
            url, 
            timeout=60,
            headers=headers,
            stream=True
        )
        response.raise_for_status()
        return response.content
    
    def _document_read(
        self,
        document_url
    ):
        """
        Reads and extracts text from a document (PDF, TXT, CSV).
        
        - If the document is a .txt or .csv it is read directly.
        - If the document is a PDF, it is processed via Google Document AI OCR.
        - Supports GCS URLs (authenticated, public, firebase) and HTTP links.

        Args:
            document_url (str): URL or path to the document.

        Returns:
            str: Extracted text content.
        """
        try:
            gcs_identifiers = ['storage.googleapis.com', 'firebasestorage.app', 'storage.cloud.google.com', 'gs://']
            is_gcs = any(id in document_url for id in gcs_identifiers)

            if is_gcs:
                print(f"Detected GCS document", flush=True)
                # Skip Document AI for native text formats
                if any(ext in document_url.lower() for ext in ['.txt', '.csv']):
                    print(f"Skipping Document AI for text-based file", flush=True)
                    return self._download_from_gcs(document_url)
                else:
                    image_content = self._download_from_gcs(document_url)
            elif document_url.startswith("http://") or document_url.startswith("https://"):
                print(f"Downloading file via HTTP", flush=True)
                image_content = self._download_from_http(document_url)
            else:
                if not os.path.exists(document_url):
                    raise FileNotFoundError(f"File not found: {document_url}")
                
                with open(document_url, "rb") as f:
                    image_content = f.read()
                print(f"Local file loaded (size: {len(image_content) / 1_024:.2f} KB)", flush=True)

            raw_doc = documentai_v1.RawDocument(
                content=image_content,
                mime_type="application/pdf"
            )

            # Verify processor name
            print(f"Using processor: {self.processor_name}", flush=True)

            # Create request
            request = documentai_v1.ProcessRequest(
                name=self.processor_name, 
                raw_document=raw_doc
            )
            print("ProcessRequest created, calling Document AI...", flush=True)
            
            # Call Document AI with explicit error handling
            try:
                result = self.docai_client.process_document(
                    request=request,
                    timeout=600.0
                )
                print("Document AI call completed successfully", flush=True)
                
            except google.api_core.exceptions.GoogleAPICallError as e:
                print(f"Document AI API error: {e}", flush=True)
                print(f"Error details: {e.details()}", flush=True)
                raise
            except google.api_core.exceptions.NotFound as e:
                print(f"Processor not found: {e}", flush=True)
                raise
            except google.api_core.exceptions.PermissionDenied as e:
                print(f"Permission denied: {e}", flush=True)
                raise
            except google.api_core.exceptions.DeadlineExceeded as e:
                print(f"Request deadline exceeded: {e}", flush=True)
                raise
            except Exception as e:
                print(f"Unexpected error during Document AI call: {type(e).__name__}", flush=True)
                print(f"Error message: {str(e)}", flush=True)
                import traceback
                print(f"Traceback: {traceback.format_exc()}", flush=True)
                raise
            
            document = result.document
            print(f"Text extraction complete, length: {len(document.text)} characters", flush=True)
            
            return document.text
        
        except Exception as e:
            print(f"Fatal error in _document_read: {type(e).__name__}: {str(e)}", flush=True)
            import traceback
            print(f"Full traceback: {traceback.format_exc()}", flush=True)
            raise
    
    def read_actions(
            self,
            user_id: str
    ) -> dict:
        """ Fetches all sustainability actions for the user. Use this when you want to look up the actions in the database.W"""
        try:
            return api_client.view_actionList(user_id)
        except Exception as e:
            return {
                "error": {e},
                "actions": []
            }
        
    def add_action(
            self,
            user_id: str,
            action_id: str,
            action_name: str,
            action_type: str,
            action_description: str,
            estimated_spend: float,
            estimated_co2_reduced: float,
            estimated_revenue_unlocked: float,
            plan_id: str,
            timeline_start: datetime,
            timeline_end: datetime,
            status: str
    ): 
        """Adds a new sustainability action to the database. This function returns the numbers of rows added to the database. Use this when you need to add a new action to the database."""
        try:
            print("Adding new action")
            action_payload = {
                "action_id": action_id,
                "action_name": action_name,
                "action_type": action_type,
                "action_description": action_description,
                "estimated_spend": estimated_spend,
                "estimated_co2_reduced": estimated_co2_reduced,
                "estimated_revenue_unlocked": estimated_revenue_unlocked,
                "plan_id": plan_id,
                "timeline_start": timeline_start.isoformat(),
                "timeline_end": timeline_end.isoformat(),
                "status": status
            }
            return api_client.add_action_service(user_id, action_payload)
        except Exception as e:
            return {
                "error": {e}
            }
        
    def remove_action(
            self,
            user_id: str,
            action_id: str
    ):
        """Removes a sustainability action from the database. Use this when you need to delete an action from the database."""
        try:
            return api_client.remove_action_service(user_id, action_id)
        except Exception as e:
            return {
                "error": {e}
            }
        
    def update_action(
            self,
            user_id: str,
            action_id: str,
            actual_co2_reduced: float,
            actual_spend: float,
            actual_revenue_unlocked: float,
            day_started: datetime,
            day_completed: datetime,
    ):
        """Updates an existing sustainability action in the database. Use this when you need to update details of an existing action."""
        try:
            update_action_payload = {
                "co2_red": actual_co2_reduced,
                "spend": actual_spend,
                "rev_unlocked": actual_revenue_unlocked,
                "day_start": day_started.isoformat() if day_started else None,
                "day_end": day_completed.isoformat() if day_completed else None,
            }
            return api_client.update_action_service(user_id, action_id, update_action_payload)
        except Exception as e:
            return {
                "error": {e}
            }

    def vertex_search(self, query: str, user_id: str):
        """
        Search user's sustainability documents (bills, emissions data, etc.) 
        to answer specific questions about their energy or environmental impact.
        
        Args:
            query: Natural language question (e.g. 'What was my electricity cost in March?')
            user_id: The ID of the user whose documents to search.
        """
        # The full resource name of the search app serving config
        serving_config = f"projects/{self.project_id}/locations/{self.location_vertexAI}/collections/default_collection/engines/{self.engine_id}/servingConfigs/default_config"

        query_understanding_spec = discoveryengine.AnswerQueryRequest.QueryUnderstandingSpec(
            query_rephraser_spec=discoveryengine.AnswerQueryRequest.QueryUnderstandingSpec.QueryRephraserSpec(
                disable=False,  # Disable query rephraser
                max_rephrase_steps=1,  # Number of rephrase steps
            ),
            # Optional: Classify query types
            query_classification_spec=discoveryengine.AnswerQueryRequest.QueryUnderstandingSpec.QueryClassificationSpec(
                types=[
                    discoveryengine.AnswerQueryRequest.QueryUnderstandingSpec.QueryClassificationSpec.Type.ADVERSARIAL_QUERY,
                    discoveryengine.AnswerQueryRequest.QueryUnderstandingSpec.QueryClassificationSpec.Type.NON_ANSWER_SEEKING_QUERY,
                ]  # Options: ADVERSARIAL_QUERY, NON_ANSWER_SEEKING_QUERY or both
            ),
        )

        answer_generation_spec = discoveryengine.AnswerQueryRequest.AnswerGenerationSpec(
            ignore_adversarial_query=False,  # Ignore adversarial query
            ignore_non_answer_seeking_query=False,  # Ignore non-answer seeking query
            ignore_low_relevant_content=False,  # Return fallback answer when content is not relevant
            model_spec=discoveryengine.AnswerQueryRequest.AnswerGenerationSpec.ModelSpec(
                model_version="stable",  # Model to use for answer generation
            ),
            prompt_spec=discoveryengine.AnswerQueryRequest.AnswerGenerationSpec.PromptSpec(
                preamble="""    
                Given the conversation between a user and a helpful assistant and some search results, create a final answer for the assistant. 
                The answer should use all relevant information from the search results, not introduce any additional information, and use exactly the same words as the search results when possible.
                """, 
            ),
            include_citations=True,  # Include citations in the response
            answer_language_code="en", 
        )

        request = discoveryengine.AnswerQueryRequest(
            serving_config=serving_config,
            query=discoveryengine.Query(text=query),
            session=None,  # Include previous session ID to continue a conversation
            query_understanding_spec=query_understanding_spec,
            answer_generation_spec=answer_generation_spec,
            user_pseudo_id=user_id,  # Add user pseudo-identifier for queries.
        )

        # Make the request
        response = self.discovery_engine_client.answer_query(request)

        return self._format_vertex_response(response)

    def _format_vertex_response(self, response):
        """Clean up the Vertex AI Search response for the LLM."""
        formatted = {
            "answer": response.answer.answer_text if response.answer else "No answer found.",
            "citations": [],
            "source_documents": []
        }

        # Extract citations
        if response.answer and response.answer.citations:
            for citation in response.answer.citations:
                formatted["citations"].append({
                    "start": citation.start_index,
                    "end": citation.end_index,
                    "reference_indices": [s.reference_id for s in citation.sources]
                })

        # Extract unique source documents and their metadata
        seen_docs = set()
        for ref in response.answer.references:
            if not ref.chunk_info or not ref.chunk_info.document_metadata:
                continue
                
            doc_meta = ref.chunk_info.document_metadata
            if doc_meta.document not in seen_docs:
                seen_docs.add(doc_meta.document)
                
                # Convert struct_data fields to a simple dict
                metadata = {}
                if doc_meta.struct_data:
                    for key, value in doc_meta.struct_data.items():
                        # Handle the nested 'data' (JSON) field or any other sub-structs
                        if hasattr(value, "items"): # It's a MapComposite or dict
                            nested = {}
                            for n_key, n_val in value.items():
                                if hasattr(n_val, "string_value"):
                                    nested[n_key] = n_val.string_value
                                elif hasattr(n_val, "number_value"):
                                    nested[n_key] = n_val.number_value
                                else:
                                    nested[n_key] = n_val
                            metadata[key] = nested
                        elif hasattr(value, "string_value"):
                            metadata[key] = value.string_value
                        elif hasattr(value, "number_value"):
                            metadata[key] = value.number_value
                        else:
                            metadata[key] = value

                formatted["source_documents"].append({
                    "id": doc_meta.document.split("/")[-1],
                    "title": doc_meta.title,
                    "uri": doc_meta.uri,
                    "metadata": metadata
                })
                
        return formatted

    def fetch_octopus_usage(self, user_id: str, days_back: int = 7, period_from: str = None, period_to: str = None):
        """Fetches electricity usage for a user from Octopus Energy. Supports specific date ranges."""
        try:
            print(f"[Tool] Fetching energy data from Octopus for user: {user_id}, range: {period_from} to {period_to}")
            # 1. Fetch energy settings from Firestore
            session_id = f"{datetime.now().strftime('%Y%m%d')}"
            firestore = FireStoreChat(user_id, session_id) 
            settings = firestore.get_user_energy_context()
            
            if not settings:
                return f"No energy settings (account number) found for user {user_id} in Firestore."
            
            account_number = settings.get("account_number")
            secret_name = settings.get("octopus_secret_name")
            
            if not all([account_number, secret_name]):
                return f"Incomplete energy settings found for user {user_id}. Need account number and secret_name."

            # 2. Fetch from API
            client = OctopusClient(self.project_id)
            api_key = client.get_secret(secret_name)
            account_data = client.get_account_details(account_number=account_number, api_key=api_key)
            mpan_list = account_data["mpan_list"]
            start_date = account_data["start_date"]

            if period_from and period_from < start_date:
                return f"No data available for the selected period. Please select a period after {start_date}"
            if period_to and period_to > datetime.now().strftime("%Y-%m-%d"):
                period_to = datetime.now().strftime("%Y-%m-%d")

            energy_data_list = []

            for mpan in mpan_list:
                for serial in mpan_list[mpan]:
                    energy_data = client.get_summarized_usage(user_id, mpan, serial, secret_name, days_back, period_from, period_to)
                    
                    if not energy_data:
                        print(f"No new data for user {user_id}.")
                        continue

                    energy_data_list.append(energy_data)
            
            if not energy_data_list:
                return "No energy consumption data found for the requested period. Ask user if they want to add new sources to cover for this period."
            
            # Format a summary for the agent to read
            summary = "Octopus Energy Report:\n"
            for data in energy_data_list:
                summary += (
                    f"- Meter {data.meter_serial} ({data.mpan}): "
                    f"{data.consumption_kwh:.2f} kWh from {data.period_start[:10]} to {data.period_end[:10]}\n"
                )
            
            return summary
        except Exception as e:
            return f"Error fetching from Octopus: {str(e)}"

    def get_tools(self) -> list[Tool]:
        google_search_tool = Tool(
            name="google_search",  # The name the LLM calls
            description="Search Google for current events and real-time facts.",
            args_schema=google_search_input,
            func=self.search_wrapper.run,
        )

        read_actions_tool = Tool(
            name = "read_actions",
            description="Reads the existing sustainability actions from the database",
            args_schema = get_api,
            func=self.read_actions
        )

        add_action_tool = StructuredTool(
            name="add_action",
            description="Adds a new sustainability action to the database. Call directly with required parameters. Do NOT use print() or wrap this call.",
            args_schema=AddActionInput,
            func=self.add_action
        )

        remove_action_tool = StructuredTool(
            name="remove_action",
            description="Removes a sustainability action from the database",
            args_schema=RemoveActionInput,
            func=self.remove_action
        )

        update_action_tool = StructuredTool(
            name="update_action",
            description="Updates an existing sustainability action in the database. Call directly with required parameters. Do NOT use print() or wrap this call.",
            args_schema=UpdateActionInput,
            func=self.update_action
        )
        
        document_read_tool = StructuredTool(
            name="document_read",
            description="""
            Extract text from files (PDF, TXT, CSV). 
            Use this to read specific sustainability reports, utility bills (PDF), or Octopus API data logs (TXT/CSV).
            Accepts: Public URLs, Firebase URLs, or GCS Console URLs (storage.cloud.google.com).
            """,
            args_schema=document_read_input,
            func=lambda document_url: self._document_read(document_url), 
        )

        vertex_search_tool = StructuredTool(
            name="vertex_search",
            description=self.vertex_search.__doc__,
            args_schema=vertex_search_input,
            func=self.vertex_search
        )
        
        octopus_fetch_tool = StructuredTool(
            name="fetch_octopus_usage",
            description="""
            Fetch LIVE energy consumption data directly from Octopus Energy API. 
            Use this if the user asks for energy data that isnt available in the database or very recent data (e.g. today or yesterday) or specifically asks for a fresh catch.
            """,
            args_schema=EnergyFetchInput,
            func=self.fetch_octopus_usage
        )

        tools_list = [google_search_tool, document_read_tool, read_actions_tool, add_action_tool, remove_action_tool, update_action_tool, vertex_search_tool, octopus_fetch_tool]

        return tools_list

# if __name__ == '__main__':
#     tool = ToolList()
#     tool.vertex_search("Tell me about my utility bills", "CORZZX0MxTQtGyAD7PSCI1HLp3y2")