import requests
from datetime import datetime, timedelta
from google.cloud import secretmanager
from chat_agent.core.models import EnergyConsumption

class OctopusClient:
    """Reusable client for Octopus Energy API."""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.api_base = "https://api.octopus.energy/v1"

    def get_secret(self, secret_id: str) -> str:
        """Fetch API Key from Secret Manager."""
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")

    def fetch_consumption(self, api_key: str, mpan: str, serial: str, days_back: int = 7):
        """Fetch consumption results from Octopus."""
        period_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
        url = f"{self.api_base}/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
        # We use standard params to avoid fetching too much data in a live tool call
        params = {"period_from": period_from, "order_by": "period"}
        
        response = requests.get(url, auth=(api_key, ""), params=params)
        response.raise_for_status()
        return response.json().get("results", [])

    def get_summarized_usage(self, user_id: str, mpan: str, serial: str, secret_name: str, days_back: int = 7) -> EnergyConsumption:
        """Fetch and aggregate consumption into a standard model."""
        api_key = self.get_secret(secret_name)
        results = self.fetch_consumption(api_key, mpan, serial, days_back)
        
        if not results:
            return None

        total_kwh = sum(r['consumption'] for r in results)
        
        return EnergyConsumption(
            user_id=user_id,
            provider="Octopus Energy",
            consumption_kwh=total_kwh,
            period_start=results[0]['interval_start'],
            period_end=results[-1]['interval_end'],
            meter_serial=serial
        )
