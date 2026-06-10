from google.cloud import bigquery, documentai_v1, storage
from google import genai
from google.cloud import discoveryengine
from google.api_core.client_options import ClientOptions
from google.genai.types import HttpOptions, GenerateContentConfig
import uuid
import json
import re
from datetime import datetime

# --- Configuration ---
PROJECT_ID = 'dash-beta-e61d0'
DATASET_ID = 'dash_beta_database'
TABLE_NAME = 'document'

# Document AI Configuration
DOCAI_LOCATION = 'eu'
PROCESSOR_ID = '77891d67fed69b99'
BUCKET_NAME = 'dash-beta-e61d0.firebasestorage.app'
FILE_PATH_PREFIX = 'gs://dash-beta-e61d0.firebasestorage.app/'

# Vertex AI Configuration
LOCATION = 'global'
GEMINI_MODEL_ID = 'gemini-3.5-flash'

# Vertex AI Search (Data Store) Configuration
DATA_STORE_LOCATION = 'eu'
DATA_STORE_ID = 'unstructureddatastore_1773747191489'
# COLLECTION_ID = 'default_collection'

class InsertException(Exception):
    def __init__(self, message):
        super().__init__(message)

# --- Clients ---
bq_client = bigquery.Client(project=PROJECT_ID)
storage_client = storage.Client()
docai_client = documentai_v1.DocumentProcessorServiceClient(
    client_options={"api_endpoint": f"{DOCAI_LOCATION}-documentai.googleapis.com"}
)
gemini_client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION,
    http_options=HttpOptions(api_version="v1")
)

def clean_llm_output(s: str) -> str:
    """Clean markdown fences and extract JSON from LLM response."""
    # remove markdown fences ```json ... ``` and leading/trailing whitespace
    s2 = re.sub(r'```json', '', s, flags=re.IGNORECASE)
    s2 = re.sub(r'```', '', s2)
    s2 = s2.replace('\\n', '\n')
    s2 = s2.strip()
    # Find the first { and last }
    m = re.search(r'(\{.*\})', s2, flags=re.DOTALL)
    if m:
        s2 = m.group(1)
    parsed = json.loads(s2)   # raises if invalid
    return json.dumps(parsed) # canonical string

def process_document(blob):
    """Pipeline for a document: OCR -> AI Extraction -> BigQuery.
    Skips OCR/LLM if it's a pre-processed .txt file (e.g. from Octopus)."""
    url = blob.name
    print(f"Processing: {url}")

    raw_text = ""
    parsed_data = {}

    metadata = blob.metadata or {}

    # Check if it's an API-generated virtual document (.txt with metadata)
    if url.endswith(".txt") and "document_type" in metadata:
        print(f"Detected virtual document: {url}")
        raw_text = blob.download_as_text()
        parsed_data = {
            "document_type": metadata.get("document_type"),
            "company_name": metadata.get("provider") or metadata.get("company_name"),
            "consumption_kwh": float(metadata.get("consumption_kwh", 0)),
            "period_start": metadata.get("period_start"),
            "period_end": metadata.get("period_end"),
            "meter_serial": metadata.get("meter_serial")
        }
    elif url.endswith(".pdf"):
        # 1. OCR with Document AI
        try: 
            processor_name = docai_client.processor_path(PROJECT_ID, DOCAI_LOCATION, PROCESSOR_ID)
            gcs_uri = f"gs://{BUCKET_NAME}/{blob.name}"
            
            docai_request = documentai_v1.ProcessRequest(
                name=processor_name,
                gcs_document=documentai_v1.GcsDocument(
                    gcs_uri=gcs_uri,
                    mime_type="application/pdf"
                )
            )
            
            docai_result = docai_client.process_document(request=docai_request, timeout=1200.0)
            raw_text = docai_result.document.text

        except Exception as e:
            print(f"Error extracting raw text using DocumentAI: {e}")

        # 2. Universal Extraction with Gemini
        response = None
        try:
            prompt = f"""
            You are a professional data extraction assistant. Analyze the following OCR text from a document and extract key information into a structured JSON format.
            
            Identify the document type (e.g., utility bill, invoice, receipt, report, etc.) and extract as many relevant fields as possible.
            
            Required Fields (if applicable):
            - document_type
            - company_name
            - industry
            - region
            - billing_start_date (YYYY-MM-DD or standard ISO)
            - billing_end_date (YYYY-MM-DD or standard ISO)
            - billing_year (integer)
            - billing_month (integer, 1-12)
            - consumption_kwh (float)
            - total_amount (float)
            - currency (string, e.g., EUR, USD)
            
            OCR Text:
            {raw_text}
            
            Return ONLY a valid JSON object.
            """

            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL_ID,
                contents=prompt,
                config=GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
        except Exception as e:
            print(f"Gemini failed to parse raw data: {e}")

        if response is not None:
            try:
                cleaned_json = clean_llm_output(response.text)
                parsed_data = json.loads(cleaned_json)
            except Exception as e:
                print(f"Error parsing Gemini response into Json: {e}")
                parsed_data = {"error": "Failed to parse LLM output", "raw_response": response.text}
    else:
        print(f"Unsupported file type: {url}")
        return

    # 3. Store in BigQuery
    try:
        document_id = str(uuid.uuid4())
        full_gs_url = FILE_PATH_PREFIX + url
        user_id = url.split("/")[1] if "/" in url else "unknown"

        row_to_insert = [{
            "document_id": document_id,
            "document_type": parsed_data.get("document_type", "unknown"),
            "raw_data": json.dumps({"document": {"text": raw_text}}),
            "parsed_data": json.dumps(parsed_data), # BigQuery JSON type
            "uploaded_time": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "source_url": full_gs_url
        }]

        table_ref = bq_client.dataset(DATASET_ID).table(TABLE_NAME)
        errors = bq_client.insert_rows_json(table_ref, row_to_insert)
        if errors:
            raise InsertException(errors)
        else:
            print("Finished ingesting document")
        
    except Exception as e:
        print(f"Failed to update table in BigQuery: {e}")

def trigger_data_store_sync():
    """Trigger a manual import from BigQuery to the Vertex AI Search Data Store."""
    print("Triggering Vertex AI Search sync...")
    try:
        client_options = (
            ClientOptions(api_endpoint=f"{DATA_STORE_LOCATION}-discoveryengine.googleapis.com")
            if DATA_STORE_LOCATION != "global"
            else None
        )

        client = discoveryengine.DocumentServiceClient(client_options=client_options)
        
        # The path of the parent resource: Data Store
        parent = client.branch_path(
            project=PROJECT_ID,
            location=DATA_STORE_LOCATION,
            data_store=DATA_STORE_ID,
            branch="default_branch"
        )

        request = discoveryengine.ImportDocumentsRequest(
            parent=parent,
            bigquery_source=discoveryengine.BigQuerySource(
                project_id=PROJECT_ID,
                dataset_id=DATASET_ID,
                table_id="RAG_unstructured", # View name in BigQuery
                data_schema="document",
            ),
            # This ensures it doesn't create duplicates and updates existing docs
            reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
        )

        operation = client.import_documents(request=request)
        print(f"Sync started. Operation name: {operation.operation.name}")
        # We don't wait for completion here to keep the function fast
        return operation
    except Exception as e:
        print(f"Failed to trigger Vertex AI Search sync: {e}")
        return None

def run_pipeline(event, context=None):
    """
    Main entry point for Cloud Run / Eventarc. 
    Handles both single-file triggers (Eventarc) and bulk sync (manual call).
    """
    # 1. Parse Event Data (Handle Flask/Functions-Framework Request objects vs Dicts)
    if hasattr(event, "get_json"):
        # If it's a Flask Request object, extract the JSON body
        try:
            event_data = event.get_json()
        except Exception:
            event_data = {}
    elif isinstance(event, dict):
        event_data = event
    else:
        event_data = {}

    # 2. Check if this is an Eventarc GCS trigger (single file)
    if event_data and "name" in event_data:
        blob_name = event_data["name"]
        print(f"Eventarc trigger detected for file: {blob_name}")

        if not (blob_name.endswith(".pdf") or blob_name.endswith(".txt")):
            print(f"Skipping unsupported file extension: {blob_name}")
            return "Skipped"

        bucket = storage_client.get_bucket(BUCKET_NAME)
        blob = bucket.get_blob(blob_name)
        if not blob:
            print(f"File {blob_name} not found in bucket.")
            return "Not Found"

        # Check if already processed
        full_url = FILE_PATH_PREFIX + blob_name
        query_check = f"SELECT COUNT(1) as cnt FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}` WHERE source_url = @url"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("url", "STRING", full_url)]
        )
        result = list(bq_client.query(query_check, job_config=job_config).result())
        
        if result[0].cnt > 0:
            print(f"File {blob_name} is already in BigQuery. Skipping to avoid duplicates.")
            return "Already Processed"

        # Process the single file
        try:
            process_document(blob)
            # Trigger sync after the new file is in BQ
            trigger_data_store_sync()
            return f"Processed single file: {blob_name}"
        except Exception as e:
            print(f"Error in single file processing: {e}")
            return f"Error: {e}"

    # 2. Fallback: Bulk Sync (Original Logic)
    print("No specific file detected in event. Starting bulk sync of bucket...")
    query_existing = f"SELECT source_url FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`"
    existing_docs = {row.source_url for row in bq_client.query(query_existing).result()}

    bucket = storage_client.get_bucket(BUCKET_NAME)
    blobs = bucket.list_blobs()

    processed_count = 0
    for blob in blobs:
        if not (blob.name.endswith(".pdf") or blob.name.endswith(".txt")):
            continue
            
        full_url = FILE_PATH_PREFIX + blob.name
        if full_url in existing_docs:
            continue

        try:
            process_document(blob)
            processed_count += 1
        except Exception as e:
            print(f"Failed to process {blob.name}: {e}")
    
    if processed_count > 0:
        trigger_data_store_sync()
    
    print(f"Bulk sync finished. Processes {processed_count} new files.")
    return f"Done (Bulk Sync: {processed_count} files)"

if __name__ == "__main__":
    run_pipeline(None, None) 