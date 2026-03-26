import sys
import os
from google.cloud import storage, firestore

from chat_agent.core.octopus import OctopusClient
from chat_agent.core.models import EnergyConsumption
from chat_agent.firestore import FireStoreChat

# --- Configuration ---
PROJECT_ID = "dash-beta-e61d0"
BUCKET_NAME = "dash-beta-e61d0.firebasestorage.app"

def upload_to_gcs(energy_data: EnergyConsumption):
    """Upload a virtual text document to GCS with standardized metadata."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    
    date_str = energy_data.period_start[:10]
    blob_path = f"users/{energy_data.user_id}/api_data/octopus/{date_str}.txt"
    blob = bucket.blob(blob_path)
    
    blob.metadata = energy_data.to_metadata()
    
    summary_text = (
        f"Daily Electricity Consumption Summary for {date_str}.\n"
        f"Provider: {energy_data.provider}\n"
        f"Total Consumption: {energy_data.consumption_kwh:.3f} kWh\n"
        f"Period: {energy_data.period_start} to {energy_data.period_end}"
    )
    
    blob.upload_from_string(summary_text, content_type="text/plain")
    return f"gs://{BUCKET_NAME}/{blob_path}"

def sync_user(user_id, settings):
    """Sync a single user's data."""
    mpan = settings.get("mpan")
    serial = settings.get("serial")
    secret_name = settings.get("octopus_secret_name")

    if not all([mpan, serial, secret_name]):
        print(f"Skipping user {user_id}: Incomplete settings.")
        return

    try:
        client = OctopusClient(PROJECT_ID)
        energy_data = client.get_summarized_usage(user_id, mpan, serial, secret_name, days_back=7)
        
        if not energy_data:
            print(f"No new data for user {user_id}.")
            return

        gcs_uri = upload_to_gcs(energy_data)
        print(f"Synced {user_id} -> {gcs_uri}")
    except Exception as e:
        print(f"Error syncing user {user_id}: {e}")

def run_bulk_sync():
    """Discover all users in Firestore and sync their energy data."""
    print("Starting bulk energy sync...")
    db = firestore.Client()
    users_ref = db.collection("users").stream()
    
    for user_doc in users_ref:
        user_id = user_doc.id
        data = user_doc.to_dict()
        
        # Check if they have energy provider enabled (default to Octopus for now)
        if data.get("octopus_secret_name") or data.get("mpan"):
            sync_user(user_id, data)

if __name__ == "__main__":
    run_bulk_sync()
