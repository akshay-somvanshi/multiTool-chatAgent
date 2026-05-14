import pandas as pd
import json
import os
import time
from google import genai
from google.cloud import bigquery
from dotenv import load_dotenv

# Load configuration
load_dotenv("chat_agent/.env")
PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
LOCATION = os.getenv("GOOGLE_LOCATION", "europe-west1")
DATASET_ID = "carbon_data"
TABLE_ID = "emission_factors"
EXCEL_PATH = "desnz_2025.xlsx"
JSONL_PATH = "desnz_2025_flattened.jsonl"

def flatten_desnz():
    """Flattens the multi-sheet DESNZ Excel into a JSONL file."""
    print(f"Reading {EXCEL_PATH}...")
    xl = pd.ExcelFile(EXCEL_PATH)
    all_records = []
    
    skip_sheets = ['Contents', 'Intro', 'Revision', 'What_is_new', 'Glossary', 'Units', 'Exclusions']
    
    for sheet in xl.sheet_names:
        if any(s in sheet for s in skip_sheets):
            continue
            
        print(f"  Flattening sheet: {sheet}...")
        try:
            df_scan = pd.read_excel(EXCEL_PATH, sheet_name=sheet, nrows=60)
            header_idx = -1
            for i, row in df_scan.iterrows():
                row_vals = [str(v).lower() for v in row.values]
                if any("unit" in v for v in row_vals) and any("co2e" in v for v in row_vals):
                    header_idx = i
                    break
            
            if header_idx == -1: continue
            
            df = pd.read_excel(EXCEL_PATH, sheet_name=sheet, skiprows=header_idx + 1)
            
            factor_col = next((c for c in df.columns if "kg co2e" in str(c).lower()), None)
            unit_col = next((c for c in df.columns if "unit" in str(c).lower()), None)
            scope_col = next((c for c in df.columns if "scope" in str(c).lower()), None)
            
            if not factor_col or not unit_col: continue
            
            unit_idx = df.columns.get_loc(unit_col)
            desc_cols = df.columns[:unit_idx].tolist()
            
            for col in desc_cols:
                df[col] = df[col].ffill()
                
            for _, row in df.iterrows():
                try:
                    val = float(row[factor_col])
                    if pd.isna(val) or (val == 0 and "outside" not in sheet.lower()): continue
                except: continue
                
                descs = [str(row[c]).strip() for c in desc_cols if pd.notna(row[c]) and str(row[c]).strip().lower() not in ['nan', 'none']]
                if not descs: continue
                
                all_records.append({
                    "activity_name": " - ".join(descs),
                    "full_description": f"{sheet} - " + " - ".join(descs),
                    "unit": str(row[unit_col]).strip(),
                    "factor": val,
                    "scope": str(row[scope_col]).strip() if scope_col and pd.notna(row[scope_col]) else "3",
                    "category": sheet,
                    "year": 2025,
                    "region": "UK"
                })
        except Exception as e:
            print(f"    [Error] {sheet}: {e}")
            
    with open(JSONL_PATH, 'w') as f:
        for r in all_records:
            f.write(json.dumps(r) + '\n')
    print(f"Flattening complete. {len(all_records)} records saved to {JSONL_PATH}")
    return all_records

def upload_to_bigquery(records):
    """Generates embeddings and uploads to BigQuery."""
    print("Initializing clients...")
    client_bq = bigquery.Client(project=PROJECT_ID)
    client_genai = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # 1. Ensure Table exists
    dataset_ref = client_bq.dataset(DATASET_ID)
    table_ref = dataset_ref.table(TABLE_ID)
    
    schema = [
        bigquery.SchemaField("activity_name", "STRING"),
        bigquery.SchemaField("full_description", "STRING"),
        bigquery.SchemaField("unit", "STRING"),
        bigquery.SchemaField("factor", "FLOAT64"),
        bigquery.SchemaField("scope", "STRING"),
        bigquery.SchemaField("category", "STRING"),
        bigquery.SchemaField("year", "INTEGER"),
        bigquery.SchemaField("region", "STRING"),
        bigquery.SchemaField("embedding", "FLOAT64", mode="REPEATED")
    ]
    
    client_bq.delete_table(table_ref, not_found_ok=True)
    table = bigquery.Table(table_ref, schema=schema)
    client_bq.create_table(table)
    print(f"Created clean table {TABLE_ID}.")
    
    # 2. Batch Embedding
    print(f"Generating embeddings for {len(records)} records...")
    batch_size = 100
    final_records = []
    
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        texts = [r['full_description'] for r in batch]
        try:
            response = client_genai.models.embed_content(
                model="text-embedding-004",
                contents=texts,
                config={"task_type": "RETRIEVAL_DOCUMENT"}
            )
            for idx, r in enumerate(batch):
                r['embedding'] = response.embeddings[idx].values
                final_records.append(r)
            print(f"  Processed {min(i+batch_size, len(records))}/{len(records)}...")
        except Exception as e:
            print(f"  Error embedding batch: {e}")
        time.sleep(0.2)
        
    # 3. Upload
    print(f"Uploading {len(final_records)} records to BQ...")
    bq_batch_size = 200
    for i in range(0, len(final_records), bq_batch_size):
        chunk = final_records[i:i+bq_batch_size]
        client_bq.insert_rows_json(table_ref, chunk)
    print("Upload complete!")

if __name__ == "__main__":
    records = flatten_desnz()
    upload_to_bigquery(records)
