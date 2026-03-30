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

    def fetch_consumption(self, api_key: str, mpan: str, serial: str, days_back: int = 7, period_from: str = None, period_to: str = None):
        """Fetch consumption results from Octopus."""
        try:
            if not period_from:
                period_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")
            
            url = f"{self.api_base}/electricity-meter-points/{mpan}/meters/{serial}/consumption/"
            params = {"period_from": period_from, "order_by": "period"}
            if period_to:
                params["period_to"] = period_to
            else:
                params["page_size"] = 1000 # Default is limited to 100 records and 7 days of record will exceed that
            
            response = requests.get(url, auth=(api_key, ""), params=params)
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            print("Error fetching consumption", e)
            return None 

    def get_account_details(self, account_number: str, api_key: str):
        try:
            url = f"{self.api_base}/accounts/{account_number}/"
            response = requests.get(url, auth=(api_key, ""))
            response.raise_for_status()
            data = response.json().get("properties", [])

            mpan_list = {}
            electricity_meters = data[0].get("electricity_meter_points", [])
            start_date = data[0].get("moved_in_at", None)

            # Get all the Mpan and their associated serial numbers in a dictionary
            for elec_meter in electricity_meters:
                mpan_list[elec_meter.get("mpan")] = []
                for meter in elec_meter.get("meters", []):
                    mpan_list[elec_meter.get("mpan")].append(meter.get("serial_number"))

            account_data =  {
                "start_date": start_date,
                "mpan_list": mpan_list
            }

            return account_data
        except Exception as e:
            print("Error fetching account details", e)
            return None

    def get_summarized_usage(self, user_id: str, mpan: str, serial: str, secret_name: str, days_back: int = 7, period_from: str = None, period_to: str = None) -> EnergyConsumption:
        """Fetch and aggregate consumption into a standard model."""
        api_key = self.get_secret(secret_name)
        results = self.fetch_consumption(api_key, mpan, serial, days_back, period_from, period_to)
        if not results:
            return None

        total_kwh = sum(r['consumption'] for r in results)
        
        return EnergyConsumption(
            user_id=user_id,
            provider="Octopus Energy",
            consumption_kwh=total_kwh,
            period_start=results[0]['interval_start'],
            period_end=results[-1]['interval_end'],
            meter_serial=serial,
            mpan=mpan
        )

# if __name__ == "__main__":
#     client = OctopusClient("dash-beta-e61d0"