from google.cloud import bigquery, documentai_v1, storage
from google import genai
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
GEMINI_MODEL_ID = 'gemini-3-flash-preview'

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
    """Pipeline for a single document: OCR -> AI Extraction -> BigQuery."""
    url = blob.name
    print(f"Processing: {url}")

    response = None

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
        
        # Increase timeout to 1200.0s, and read directly from GCS 
        # to avoid large file downloading SSL dropout 
        docai_result = docai_client.process_document(request=docai_request, timeout=1200.0)
        raw_text = docai_result.document.text

    except Exception as e:
        print(f"Error extracting raw text using DocumentAI: {e}")

    # 2. Universal Extraction with Gemini
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
            # Make it a dict to extract document type 
            parsed_data = json.loads(cleaned_json)
        except Exception as e:
            print(f"Error parsing Gemini response into Json: {e}")
            parsed_data = {"error": "Failed to parse LLM output", "raw_response": response.text}

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
        # update_query = f"""
        #     UPDATE {PROJECT_ID}.{DATASET_ID}.{TABLE_NAME} 
        #     SET parsed_data= @parsed_data
        #     WHERE document_id= @document_id"""
        
        # update_job = bq_client.query(
        #     update_query, 
        #     job_config=bigquery.QueryJobConfig(
        #         query_parameters=[
        #             bigquery.ScalarQueryParameter("parsed_data", "JSON", parsed_data),
        #             bigquery.ScalarQueryParameter("document_id", "STRING", document_id)
        #         ]
        #     ),
        # ).result()
        
    except Exception as e:
        print(f"Failed to update table in BigQuery: {e}")

def run_pipeline(event, context=None):
    # Get existing documents to avoid duplicates
    query_existing = f"SELECT source_url FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_NAME}`"
    existing_docs = {row.source_url for row in bq_client.query(query_existing).result()}

    bucket = storage_client.get_bucket(BUCKET_NAME)
    blobs = bucket.list_blobs()

    for blob in blobs:
        if not blob.name.endswith(".pdf"):
            continue
            
        full_url = FILE_PATH_PREFIX + blob.name
        if full_url in existing_docs:
            print(f"Skipping already processed document: {blob.name}")
            continue

        try:
            process_document(blob)
        except Exception as e:
            print(f"Failed to process {blob.name}: {e}")
    
    return "Done"
