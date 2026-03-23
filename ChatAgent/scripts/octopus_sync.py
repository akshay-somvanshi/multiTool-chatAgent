from google.cloud import secretmanager, storage
import json
import sys
import os
from datetime import datetime, timedelta
import requests

from chat_agent.core.models import EnergyConsumption

# --- Configuration ---
PROJECT_ID = "dash-beta-e61d0"
BUCKET_NAME = "dash-beta-e61d0.firebasestorage.app"
OCTOPUS_API_BASE = "https://api.octopus.energy/v1"

def get_secret(secret_id):
    """Fetch user's Octopus API Key from Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def fetch_consumption(api_key, mpan, serial, days_back=30):
    """Fetch electricity consumption for the requested period."""
    period_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
    
    url = f"{OCTOPUS_API_BASE}/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
    params = {"period_from": period_from, "order_by": "period"}
    
    response = requests.get(url, auth=(api_key, "")) #, params=params)
    response.raise_for_status()
    # print("Response", response.json())
    return response.json().get("results", [])

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
    """Fetch from API and upload to GCS using Pydantic for standardization."""
    print(f"Syncing Octopus data for {user_id}...")
    
    api_key = get_secret(secret_name)
    results = fetch_consumption(api_key, mpan, serial)
    
    if not results:
        print("No consumption data found.")
        return

    # 1. Aggregate data from Octopus response
    total_kwh = sum(r['consumption'] for r in results)
    
    # 2. Create standardized model
    energy_data = EnergyConsumption(
        user_id=user_id,
        provider="Octopus Energy",
        consumption_kwh=total_kwh,
        period_start=results[0]['interval_start'],
        period_end=results[-1]['interval_end'],
        meter_serial=serial
    )

    print(energy_data)
    # 3. Upload to GCS
    # gcs_uri = upload_to_gcs(energy_data)
    # print(f"Successfully uploaded to {gcs_uri}")

if __name__ == "__main__":
    run_sync("CORZZX0MxTQtGyAD7PSCI1HLp3y2", "1200050349332", "23M0382483", "CORZZX0MxTQtGyAD7PSCI1HLp3y2_Octopus_key")
