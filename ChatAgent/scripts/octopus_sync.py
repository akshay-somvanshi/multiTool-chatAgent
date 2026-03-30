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
    mpan = energy_data.mpan
    serial = energy_data.meter_serial

    blob_path = f"users/{energy_data.user_id}/api_data/octopus/{mpan}_{serial}_{date_str}.txt"
    blob = bucket.blob(blob_path)
    
    blob.metadata = energy_data.to_metadata()
    
    summary_text = (
        f"Daily Electricity Consumption Summary for {date_str}.\n"
        f"Provider: {energy_data.provider}\n"
        f"Total Consumption: {energy_data.consumption_kwh:.3f} kWh\n"
        f"Period: {energy_data.period_start} to {energy_data.period_end}\n"
        f"MPAN: {mpan}\n"
        f"Meter Serial: {energy_data.meter_serial}\n"
    )

    blob.upload_from_string(summary_text, content_type="text/plain")
    return f"gs://{BUCKET_NAME}/{blob_path}"

def sync_user(user_id, settings):
    """Sync a single user's data."""
    account_number = settings.get("octopus_account_num")
    secret_name = settings.get("octopus_secret_name")

    if not all([account_number, secret_name]):
        print(f"Skipping user {user_id}: Incomplete settings.")
        return

    try:
        client = OctopusClient(PROJECT_ID)
        api_key = client.get_secret(secret_name)
        account_data = client.get_account_details(account_number=account_number, api_key=api_key)
        mpan_list = account_data["mpan_list"]

        for mpan in mpan_list:
            for serial in mpan_list[mpan]:
                energy_data = client.get_summarized_usage(user_id, mpan, serial, secret_name, days_back=7)
                
                if not energy_data:
                    print(f"No new data for user {user_id}.")
                    continue

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
        
        if data.get("octopus_secret_name") or data.get("octopus_account_num"):
            sync_user(user_id, data)

if __name__ == "__main__":
    run_bulk_sync()
