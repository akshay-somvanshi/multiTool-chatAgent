from langchain_core.tools import tool, Tool, StructuredTool
from google import genai
from fpdf import FPDF
from langchain_google_community import GoogleSearchAPIWrapper
from pydantic import BaseModel, Field
from google.api_core.client_options import ClientOptions
from google.cloud import discoveryengine_v1 as discoveryengine
from google.cloud import documentai_v1
import os
import dotenv
import requests
import google
from urllib.parse import urlparse, parse_qs, unquote
from google.cloud import storage
from google.cloud import bigquery
from datetime import datetime
import pandas as pd
import io

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

class SustainabilityROIInput(BaseModel):
    user_id: str = Field(description="User ID")
    new_revenue: float = Field(description="New revenue generated this year from sustainability initiatives (£)")
    retained_revenue: float = Field(description="Revenue retained this year due to sustainability initiatives (£)")
    ops_cost_reduction: float = Field(description="Operational costs reduced this year (£)")
    risk_minimized: float = Field(description="Estimated value of business risk minimized (£)")
    ops_cost_reduction_5y: float = Field(description="Total operational costs reduced in the next 5 years (£)")
    financing_cost_diff: float = Field(description="Difference in cost of financing (Year 1 - Year 0) (£)")
    spend_this_year: float = Field(description="Total spend on sustainability this year (£)")

class IndustryInfoInput(BaseModel):
    industry_name: str = Field(description="The name of the industry to look up guidelines for (e.g., 'Retail', 'Manufacturing')")

class PDFGeneratorInput(BaseModel):
    title: str = Field(description="The title shown inside the report")
    content: str = Field(description="The text content of the report. Use \n for new lines.")
    user_id: str = Field(description="The user ID to associate the report with")
    company_name: str = Field(description="The name of the company (used for filename)")
    report_type: str = Field(description="The type of report, e.g. 'Sustainability plan', 'CDP document' (used for filename)")

class CarbonCalculationInput(BaseModel):
    activity_name: str = Field(description="The name of the activity (e.g., 'Electricity', 'Petrol', 'Natural Gas', 'Short-haul Flight')")
    amount: float = Field(description="The numerical value of the activity (e.g., 500)")
    unit: str = Field(description="The unit for the activity (e.g., 'kWh', 'litres', 'passenger-km', 'tonnes')")

class BulkReadinessInput(BaseModel):
    gcs_uri: str = Field(description="The Gcs URI (folder) to check for documents (e.g., gs://bucket/user/uploads/)")
    expected_categories: list[str] = Field(default=[], description="Optional list of categories the user expects to find (e.g. ['Electricity', 'Fuel'])")

class BulkProcessInput(BaseModel):
    gcs_uri: str = Field(description="The GCS URI (folder) to process documents from")
    user_id: str = Field(description="The user ID to associate results with")

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
        self.bq_client = bigquery.Client(project=self.project_id)
        self.genai_client = genai.Client(
            vertexai=True,
            project=self.project_id,
            location="global"
        )

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

            # Decode URL-encoded characters in the blob path (like %20 for spaces)
            blob_path = unquote(blob_path)
            print(f"Downloading from GCS: bucket={bucket_name}, path={blob_path}", flush=True)
            
            storage_client = storage.Client(project=self.project_id)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            # Simple text vs bytes logic
            # .xlsx is a binary format, MUST be bytes
            if blob_path.lower().endswith('.txt') or blob_path.lower().endswith('.csv'):
                print(f"Downloading {blob_path} as text", flush=True)
                content = blob.download_as_text()
            else:
                print(f"Downloading {blob_path} as bytes", flush=True)
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
        print(f"[Tool] Starting document_read for: {document_url}", flush=True)
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
                elif '.xlsx' in document_url.lower():
                    print(f"Reading Excel file for text extraction", flush=True)
                    content = self._download_from_gcs(document_url)
                    df = pd.read_excel(io.BytesIO(content))
                    return df.to_csv(index=False)
                else:
                    image_content = self._download_from_gcs(document_url)
            elif document_url.startswith("http://") or document_url.startswith("https://"):
                print(f"Downloading file via HTTP", flush=True)
                # Handle direct Excel/CSV over HTTP as well
                if any(ext in document_url.lower() for ext in ['.txt', '.csv']):
                    return self._download_from_http(document_url).decode('utf-8', errors='replace')
                elif '.xlsx' in document_url.lower():
                    content = self._download_from_http(document_url)
                    df = pd.read_excel(io.BytesIO(content))
                    return df.to_csv(index=False)
                
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

    def calculate_sustainability_roi(
        self,
        user_id: str,
        new_revenue: float,
        retained_revenue: float,
        ops_cost_reduction: float,
        risk_minimized: float,
        ops_cost_reduction_5y: float,
        financing_cost_diff: float,
        spend_this_year: float
    ) -> dict:
        """
        Calculates the Return on Investment (ROI) for a sustainability action using a weighted formula.
        The weights (probabilities) are fetched from the system configuration.
        """
        try:
            # Fetch probabilities from Firestore
            session_id = f"roi_{datetime.now().strftime('%Y%m%d')}"
            firestore = FireStoreChat(user_id, session_id)
            p = firestore.get_roi_probabilities()

            # Apply formula
            # ROI = {(New Revenue * P1) + (Retained Revenue * P2) + (Ops cost reduced * P3) + 
            #        (Risk minimized * P4) + (Ops costs reduced 5y * P5) + (Diff in financing cost * P6)} - Spend
            
            revenue_unlocked = (
                (new_revenue * p["p1_new_revenue"]) +
                (retained_revenue * p["p2_retained_revenue"]) +
                (ops_cost_reduction * p["p3_ops_cost_reduction"]) +
                (risk_minimized * p["p4_risk_minimized"]) +
                (ops_cost_reduction_5y * p["p5_ops_cost_reduction_5y"]) +
                (financing_cost_diff * p["p6_financing_cost_diff"])
            )
            
            roi = revenue_unlocked - spend_this_year

            return {
                "estimated_revenue_unlocked": round(revenue_unlocked, 2),
                "total_roi": round(roi, 2),
                "applied_weights": p,
                "currency": "GBP"
            }
        except Exception as e:
            print(f"ROI Calculation failed: {e}", flush=True)
            return {"error": str(e)}

    def get_industry_guidelines(self, industry_name: str) -> dict:
        """
        Fetches industry-specific procurement policies and recommended actions from BigQuery.
        """
        try:
            dataset_id = "dash_beta_database"
            table_id = "industry_guidelines"
            query = f"""
                SELECT policy_document, predefined_actions, key_questions 
                FROM `{self.project_id}.{dataset_id}.{table_id}` 
                WHERE LOWER(industry_name) = @industry
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("industry", "STRING", industry_name.lower())
                ]
            )
            
            query_job = self.bq_client.query(query, job_config=job_config)
            results = list(query_job.result())

            if not results:
                return {"message": f"No specific guidelines found for industry: {industry_name}"}

            row = results[0]
            
            # Parse JSON fields if they are stored as strings
            def safe_json_load(data):
                if isinstance(data, str):
                    try:
                        import json
                        return json.loads(data)
                    except:
                        return data
                return data

            return {
                "industry": industry_name,
                "policy_document": row.policy_document,
                "predefined_actions": safe_json_load(row.predefined_actions),
                "key_questions": safe_json_load(row.key_questions)
            }

        except Exception as e:
            print(f"Error fetching industry guidelines: {e}")
            return {"error": str(e)}
        
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
        """Fetches electricity usage and cost for a user from Octopus Energy. Supports specific date ranges."""
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
                    f"Total Cost: £{data.total_cost_gbp:.2f}\n"
                )

            return summary

        except Exception as e:
            print(f"[Tool] Failed to get report from Octopus Energy: {str(e)}", flush=True)
            return f"Error fetching from Octopus: {str(e)}"

    def _generate_pdf_report(self, title: str, content: str, user_id: str, company_name: str, report_type: str) -> str:
        """
        Generates a PDF report, uploads it to GCS, and returns the URL.
        Filename format: companyName_reportType.pdf
        """
        try:
            print(f"[Tool] Generating PDF report for {company_name}: {report_type}", flush=True)
            pdf = FPDF()
            pdf.add_page()
            
            # Title
            pdf.set_font("helvetica", "B", 16)
            pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.ln(10)
            
            # Content
            pdf.set_font("helvetica", "", 12)
            # Replace unsupported characters to avoid FPDF errors
            clean_content = content.encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 10, clean_content)
            
            # Sanitize and construct filename
            safe_company = company_name.replace(" ", "").replace("/", "_")
            safe_type = report_type.replace(" ", "").replace("/", "_")
            filename = f"{safe_company}_{safe_type}.pdf"
            
            temp_path = f"/tmp/{filename}"
            pdf.output(temp_path)
            
            # Upload to GCS
            bucket_name = f"{self.project_id}.firebasestorage.app"
            storage_client = storage.Client(project=self.project_id)
            bucket = storage_client.bucket(bucket_name)
            blob = bucket.blob(f"users/{user_id}/reports/{filename}")
            
            blob.upload_from_filename(temp_path)
            
            # Construct the public URL
            url = f"https://storage.googleapis.com/{bucket_name}/users/{user_id}/reports/{filename}"
            
            # Cleanup
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            print(f"[Tool] PDF report generated and uploaded: {filename}", flush=True)
            return f"PDF report '{filename}' generated successfully. You can access it in the Knowledge page."
            
            print(f"Error generating PDF: {e}", flush=True)
            return f"Failed to generate PDF. Please try again."

        except Exception as e:
            print(f"Error generating PDF: {e}", flush=True)
            return f"Failed to generate PDF. Please try again."

    def _calculate_carbon_footprint(self, activity_name: str, amount: float, unit: str) -> dict:
        """
        Calculates carbon emissions (kgCO2e) by querying the BigQuery emission factors table.
        """
        try:
            print(f"[Tool] Calculating carbon footprint for: {activity_name} ({amount} {unit})", flush=True)
            dataset_id = "dash_beta_database"
            table_id = "emission_factors"
            
            query = f"""
                SELECT factor, scope, category, region 
                FROM `{self.project_id}.{dataset_id}.{table_id}` 
                WHERE LOWER(activity_name) = @activity 
                AND LOWER(unit) = @unit
                ORDER BY year DESC
                LIMIT 1
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("activity", "STRING", activity_name.lower()),
                    bigquery.ScalarQueryParameter("unit", "STRING", unit.lower())
                ]
            )
            
            query_job = self.bq_client.query(query, job_config=job_config)
            results = list(query_job.result())

            if not results:
                return {
                    "error": f"No emission factor found for '{activity_name}' in '{unit}'. Try using different keywords or checking available units (e.g., kWh, litres, tonnes, passenger-km)."
                }

            row = results[0]
            emissions = amount * row.factor

            return {
                "activity": activity_name,
                "amount": amount,
                "unit": unit,
                "emissions_kgCO2e": round(emissions, 3),
                "scope": f"Scope {row.scope}",
                "category": row.category,
                "region": row.region,
                "note": "Calculated using open-source conversion factors (DEFRA/EPA)."
            }

        except Exception as e:
            print(f"Error calculating carbon footprint: {e}", flush=True)
            return {"error": str(e)}

    def _calculate_emissions_batch_bq(self, activities: list[dict], user_id: str) -> dict:
        """
        Analytical calculation: Loads activities to a temp BQ table and joins with factors.
        This is the high-performance path for large datasets.
        """
        try:
            print(f"[Tool] Batch calculating emissions for {len(activities)} activities", flush=True)
            dataset_id = "dash_beta_database"
            # Sanitize user_id for table name
            safe_user_id = user_id.replace("-", "_").replace(".", "_")
            temp_table_id = f"temp_staging_{safe_user_id}"
            full_table_name = f"{self.project_id}.{dataset_id}.{temp_table_id}"
            
            # 1. Load data to BQ
            job_config = bigquery.LoadJobConfig(
                write_disposition="WRITE_TRUNCATE",
                autodetect=True,
            )
            load_job = self.bq_client.load_table_from_json(activities, full_table_name, job_config=job_config)
            load_job.result() # Wait for completion
            
            # 2. Run Analytical Join
            query = f"""
                WITH calculated AS (
                    SELECT 
                        s.*,
                        f.factor,
                        f.scope,
                        f.category as factor_category,
                        CAST(s.amount AS FLOAT64) * f.factor as co2_kg
                    FROM `{full_table_name}` s
                    JOIN `{self.project_id}.{dataset_id}.emission_factors` f
                      ON LOWER(s.activity_name) = LOWER(f.activity_name)
                     AND LOWER(s.unit) = LOWER(f.unit)
                )
                SELECT 
                    scope,
                    factor_category as category,
                    SUM(co2_kg) as total_co2,
                    SUM(CAST(amount AS FLOAT64)) as total_amount,
                    unit,
                    COUNT(*) as count
                FROM calculated
                GROUP BY 1, 2, 5
            """
            query_job = self.bq_client.query(query)
            results = list(query_job.result())
            
            # 3. Format results
            summary = []
            grand_total = 0.0
            for row in results:
                summary.append({
                    "scope": row.scope,
                    "category": row.category,
                    "total_co2_kg": round(row.total_co2, 2),
                    "total_amount": row.total_amount,
                    "unit": row.unit,
                    "count": row.count
                })
                grand_total += row.total_co2
            
            # Cleanup temp table
            self.bq_client.delete_table(full_table_name, not_found_ok=True)
            
            return {
                "total_emissions_kgCO2e": round(grand_total, 2),
                "breakdown": summary,
                "status": "success",
                "processed_count": len(activities)
            }
        except Exception as e:
            print(f"Error in batch calculation: {e}", flush=True)
            try:
                self.bq_client.delete_table(full_table_name, not_found_ok=True)
            except: pass
            return {"error": str(e)}

    def _calculate_emissions_from_file_bq(self, gcs_uri: str, user_id: str) -> dict:
        """
        Reads Excel/CSV from GCS and processes via BigQuery analytical engine.
        Handles large data files without row-by-row LLM extraction if the file is already structured.
        """
        try:
            print(f"[Tool] Processing structured file from GCS: {gcs_uri}", flush=True)
            content = self._download_from_gcs(gcs_uri)
            
            # Read into Pandas
            if gcs_uri.lower().endswith(".xlsx"):
                df = pd.read_excel(io.BytesIO(content))
            else:
                if isinstance(content, str):
                    df = pd.read_csv(io.StringIO(content))
                else:
                    df = pd.read_csv(io.BytesIO(content))
            
            # Sanitize columns
            df.columns = [str(c).replace(' ', '_').replace('(', '').replace(')', '').lower() for c in df.columns]
            
            rename_map = {}
            col_lower = [c.lower() for c in df.columns]
            
            for syn in ['item', 'activity', 'description', 'name', 'product']:
                if syn in col_lower:
                    idx = col_lower.index(syn)
                    rename_map[df.columns[idx]] = 'activity_name'
                    break
            
            for syn in ['qty', 'quantity', 'amount', 'value', 'usage']:
                if syn in col_lower:
                    idx = col_lower.index(syn)
                    rename_map[df.columns[idx]] = 'amount'
                    break

            for syn in ['unit', 'measure', 'uom']:
                if syn in col_lower:
                    idx = col_lower.index(syn)
                    rename_map[df.columns[idx]] = 'unit'
                    break
            
            if rename_map:
                df = df.rename(columns=rename_map)
            
            required = ['activity_name', 'amount', 'unit']
            missing = [r for r in required if r not in df.columns]
            if missing:
                return {"error": f"Missing required columns in file: {missing}. Please ensure your file has columns for Activity, Amount, and Unit."}

            activities = df[required].to_dict(orient="records")
            return self._calculate_emissions_batch_bq(activities, user_id)
            
        except Exception as e:
            print(f"Error processing file for BQ: {e}", flush=True)
            return {"error": str(e)}


    def _check_bulk_readiness(self, gcs_uri: str, expected_categories: list[str] = []) -> dict:
        """
        Scans a GCS folder to check if all necessary documents are available before bulk processing.
        """
        try:
            print(f"[Tool] Checking bulk readiness for: {gcs_uri}", flush=True)
            
            # Parse GCS URI
            if not gcs_uri.startswith("gs://"):
                return {"error": "Invalid URI. Must start with gs://"}
            
            parts = gcs_uri.replace("gs://", "").split("/", 1)
            bucket_name = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
            
            storage_client = storage.Client(project=self.project_id)
            bucket = storage_client.bucket(bucket_name)
            # List blobs with the given prefix
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            if not blobs:
                return {"error": "No files found in the specified GCS path."}
            
            file_summary = []
            categories_found = set()
            
            for blob in blobs:
                # Basic check to skip folders (some GCS providers create empty objects ending in /)
                if blob.name.endswith("/"): continue 
                
                filename = blob.name.split("/")[-1]
                if not filename: continue # Skip if it's just the prefix
                
                size_kb = blob.size / 1024
                
                # Simple keyword matching for categories from filename
                category = "Other"
                keywords = {
                    "Electricity": ["elec", "bill", "utility", "power", "enel", "octopus"],
                    "Fuel": ["fuel", "petrol", "diesel", "gasoline", "gas station"],
                    "Travel": ["flight", "hotel", "travel", "train", "airline", "booking"],
                    "Water": ["water", "sewage"],
                    "Waste": ["waste", "recycling", "trash"]
                }
                
                for cat, keys in keywords.items():
                    if any(k in filename.lower() for k in keys):
                        category = cat
                        categories_found.add(cat)
                        break
                
                file_summary.append({
                    "filename": filename,
                    "category_guess": category,
                    "size_kb": round(size_kb, 2),
                    "last_modified": blob.updated.strftime("%Y-%m-%d")
                })
            
            missing_categories = [cat for cat in expected_categories if cat.lower() not in [c.lower() for c in categories_found]]
            
            return {
                "total_files": len(file_summary),
                "categories_detected": list(categories_found),
                "missing_expected_categories": missing_categories,
                "file_list": file_summary[:20], # Return a snippet for the agent
                "ready_to_process": len(missing_categories) == 0,
                "message": "Folder check complete."
            }

        except Exception as e:
            print(f"Error checking bulk readiness: {e}", flush=True)
            return {"error": str(e)}

    def _extract_activities_from_text(self, text: str) -> list[dict]:
        """
        Uses Gemini to extract sustainability activities (Activity, Amount, Unit) from raw text.
        """
        prompt = f"""
        Extract sustainability-related activities from the following document text.
        Focus on energy consumption, fuel usage, travel (flights/hotel), water, and waste.
        
        Return a JSON list of objects with these keys:
        - activity_name: (e.g. "Electricity", "Petrol", "Short-haul Flight")
        - amount: (The numerical value)
        - unit: (e.g. "kWh", "litres", "passenger-km", "tonnes")
        - category: (e.g. "Energy", "Transport", "Travel")
        - date: (ISO format if found, otherwise null)
        
        Text:
        {text}
        
        JSON Result:
        """
        try:
            response = self.genai_client.models.generate_content(
                model="gemini-3-flash-preview",
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                }
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"Error in LLM extraction: {e}", flush=True)
            return []

    def _process_bulk_sustainability_data(self, gcs_uri: str, user_id: str) -> dict:
        """
        Bulk processes documents from GCS, extracts activities, and calculates carbon footprint.
        Now uses BigQuery analytical engine for high-performance batch calculation.
        """
        try:
            print(f"[Tool] Starting bulk processing for: {gcs_uri}", flush=True)
            
            # 1. Gather all blobs
            if not gcs_uri.startswith("gs://"):
                return {"error": "Invalid URI. Must start with gs://"}
            
            parts = gcs_uri.replace("gs://", "").split("/", 1)
            bucket_name = parts[0]
            prefix = parts[1] if len(parts) > 1 else ""
            
            storage_client = storage.Client(project=self.project_id)
            bucket = storage_client.bucket(bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            if not blobs:
                return {"error": "No files found in the specified GCS path."}
            
            all_activities = []
            processed_count = 0
            
            for blob in blobs:
                if blob.name.endswith("/"): continue
                
                filename = blob.name.split("/")[-1]
                if not filename: continue
                
                print(f"[Tool] Processing file: {filename}", flush=True)
                
                # 2. Extract Text
                text = ""
                if blob.name.lower().endswith(".pdf"):
                    text = self._document_read(f"gs://{bucket_name}/{blob.name}")
                else:
                    text = blob.download_as_text()
                
                if not text or "Error" in text[:50]: 
                    continue
                
                # 3. Extract Activities via LLM
                activities = self._extract_activities_from_text(text)
                for act in activities:
                    # Sanitize amount to float
                    try:
                        act["amount"] = float(act.get("amount", 0))
                    except:
                        act["amount"] = 0.0
                    act["source_file"] = filename
                    all_activities.append(act)
                
                processed_count += 1

            # 4. Batch Calculate via BigQuery Analytical Engine
            if not all_activities:
                return {"error": "No sustainability activities were found in the provided documents."}

            batch_results = self._calculate_emissions_batch_bq(all_activities, user_id)
            
            if "error" in batch_results:
                return batch_results

            return {
                "total_files_processed": processed_count,
                "total_activities_found": len(all_activities),
                "total_emissions_kgCO2e": batch_results["total_emissions_kgCO2e"],
                "emissions_breakdown": batch_results["breakdown"],
                "activities_sample": all_activities[:15],
                "ready_for_report": True
            }

        except Exception as e:
            print(f"Error in bulk processing: {e}", flush=True)
            return {"error": str(e)}

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
            Fetch LIVE energy consumption data and cost directly from Octopus Energy API. 
            Use this if the user asks for energy data that isnt available in the database or very recent data (e.g. today or yesterday) or specifically asks for a fresh catch.
            """,
            args_schema=EnergyFetchInput,
            func=self.fetch_octopus_usage
        )

        calculate_roi_tool = StructuredTool(
            name="calculate_sustainability_roi",
            description="""
            Calculates the financial ROI for a sustainability action. 
            Use this tool BEFORE calling add_action if you need to determine the 'estimated_revenue_unlocked'.
            You must estimate the formula components (new revenue, retained revenue, etc.) based on the action details.
            """,
            args_schema=SustainabilityROIInput,
            func=self.calculate_sustainability_roi
        )

        industry_guidelines_tool = StructuredTool(
            name="get_industry_guidelines",
            description="""
            Fetches industry-specific procurement policies and recommended actions.
            Use this tool to understand the constraints and standard actions for the user's specific industry.
            """,
            args_schema=IndustryInfoInput,
            func=self.get_industry_guidelines
        )

        generate_pdf_tool = StructuredTool(
            name="generate_pdf_report",
            description="""
            Generates a professional PDF report from text content. 
            Use this when the user specifically asks for a PDF version of a summary, report, or analysis.
            """,
            args_schema=PDFGeneratorInput,
            func=self._generate_pdf_report
        )

        calculate_carbon_tool = StructuredTool(
            name="calculate_carbon_footprint",
            description="""
            Calculates carbon emissions (kgCO2e) based on activity data. 
            Covers Scope 1 (fuel), Scope 2 (electricity), and Scope 3 (travel, water, waste).
            Always ask for activity type (e.g. Electricity), amount (e.g. 500) and unit (e.g. kWh).
            """,
            args_schema=CarbonCalculationInput,
            func=self._calculate_carbon_footprint
        )

        check_readiness_tool = StructuredTool(
            name="check_bulk_readiness",
            description="""
            Checks a GCS folder for documents before starting a bulk sustainability analysis. 
            Identifies file types and detects categories (Electricity, Fuel, Travel, etc.) from filenames.
            Use this to confirm with the user that all data is present before starting a long process.
            """,
            args_schema=BulkReadinessInput,
            func=self._check_bulk_readiness
        )

        bulk_process_tool = StructuredTool(
            name="process_bulk_sustainability_data",
            description="""
            Bulk processes documents (PDF/TXT) from a GCS folder. 
            Extracts activities using Document AI and Gemini, then calculates total carbon footprint using BigQuery's analytical engine.
            This is a long-running process. Always call check_bulk_readiness first.
            """,
            args_schema=BulkProcessInput,
            func=self._process_bulk_sustainability_data
        )

        calculate_bulk_file_tool = StructuredTool(
            name="calculate_emissions_from_structured_file",
            description="""
            Calculates carbon emissions for a large structured file (CSV/Excel) in GCS.
            The file MUST have columns for:
            1. 'Activity' (or 'Item', 'Description'): e.g., 'Electricity', 'Petrol'
            2. 'Amount' (or 'Qty', 'Usage'): e.g., 500
            3. 'Unit' (or 'Measure', 'UOM'): e.g., 'kWh', 'litres'
            This uses BigQuery's analytical engine for high-performance processing of thousands of rows.
            """,
            args_schema=BulkProcessInput,
            func=self._calculate_emissions_from_file_bq
        )

        tools_list = [
            google_search_tool, 
            document_read_tool, 
            read_actions_tool, 
            add_action_tool, 
            remove_action_tool, 
            update_action_tool, 
            vertex_search_tool, 
            octopus_fetch_tool, 
            calculate_roi_tool, 
            industry_guidelines_tool, 
            generate_pdf_tool, 
            check_readiness_tool, 
            bulk_process_tool,
            calculate_bulk_file_tool
        ]

        return tools_list

# if __name__ == '__main__':
#     tool = ToolList()
#     tool.vertex_search("Tell me about my utility bills", "CORZZX0MxTQtGyAD7PSCI1HLp3y2")