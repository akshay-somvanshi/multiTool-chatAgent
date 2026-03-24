import sys
import os
from google.cloud import storage

from chat_agent.core.octopus import OctopusClient
from chat_agent.core.models import EnergyConsumption

# --- Configuration ---
PROJECT_ID = "dash-beta-e61d0"
BUCKET_NAME = "dash-beta-e61d0.firebasestorage.app"

def upload_to_gcs(energy_data: EnergyConsumption):
    """Upload a virtual text document to GCS with standardized metadata."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    
    date_str = energy_data.period_start[:10]
    blob_path = f"api_data/octopus/{energy_data.user_id}/{date_str}.txt"
    blob = bucket.blob(blob_path)
    
    # Use the model's standardized metadata
    blob.metadata = energy_data.to_metadata()
    
    summary_text = (
        f"Daily Electricity Consumption Summary for {date_str}.\n"
        f"Provider: {energy_data.provider}\n"
        f"Total Consumption: {energy_data.consumption_kwh:.3f} kWh\n"
        f"Period: {energy_data.period_start} to {energy_data.period_end}"
    )
    
    blob.upload_from_string(summary_text, content_type="text/plain")
    return f"gs://{BUCKET_NAME}/{blob_path}"

def run_sync(user_id, mpan, serial, secret_name):
    """Background sync using the reusable OctopusClient."""
    print(f"Syncing Octopus data for {user_id}...")
    
    client = OctopusClient(PROJECT_ID)
    energy_data = client.get_summarized_usage(user_id, mpan, serial, secret_name, days_back=7)
    
    if not energy_data:
        print("No consumption data found.")
        return

    # print(f"Aggregated Data: {energy_data}")
    
    # Upload to GCS to trigger the main ingestion pipeline
    gcs_uri = upload_to_gcs(energy_data)
    print(f"Successfully uploaded to {gcs_uri}")

if __name__ == "__main__":
    # Example for the user
    run_sync(
        user_id="CORZZX0MxTQtGyAD7PSCI1HLp3y2", 
        mpan="1200050349332", 
        serial="23M0382483", 
        secret_name="CORZZX0MxTQtGyAD7PSCI1HLp3y2_Octopus_key"
    )
