import requests
import json
from datetime import datetime, timedelta
from google.cloud import secretmanager
from chat_agent.core.models import SAPProductOrderItem

# Mock database for Material and Supplier lookups
MOCK_MATERIALS = {
    "68": {"name": "High-Grade Steel", "weight_per_unit": 10.5, "co2_factor": 1.85},
    "21": {"name": "Recycled Aluminum", "weight_per_unit": 2.2, "co2_factor": 0.45},
}
MOCK_SUPPLIERS = {
    "10001": {"name": "EcoSteel UK Ltd"},
    "10002": {"name": "Global Metals Corp"},
}

class SAPClient:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.sandbox_url = "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/purchaseorder/0001"

    def get_secret(self, secret_id: str) -> str:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")

    def _enrich_item(self, item_data: dict, creation_date: str, supplier_code: str) -> SAPProductOrderItem:
        """Helper to calculate sustainability metrics and enrich with mock master data."""
        material_id = item_data.get("Material", "")
        
        # 1. Lookups
        material_info = MOCK_MATERIALS.get(material_id, {"name": "Unknown Material", "weight_per_unit": 0, "co2_factor": 0})
        supplier_info = MOCK_SUPPLIERS.get(supplier_code, {"name": "Unknown Supplier"})

        # 2. Calculations
        net_price = float(item_data.get("NetPriceAmount", 0))
        net_price_qty = int(item_data.get("NetPriceQuantity", 1))
        order_qty = int(item_data.get("OrderQuantity", 0))
        
        # SAP Pricing: Price is per 'NetPriceQuantity' units
        total_cost = net_price * (order_qty / net_price_qty)
        total_weight = order_qty * material_info["weight_per_unit"]
        co2_impact = total_weight * material_info["co2_factor"]

        return SAPProductOrderItem(
            PurchaseOrder=item_data.get("PurchaseOrder"),
            PurchaseOrderItem=item_data.get("PurchaseOrderItem"),
            PurchaseOrderItemText=item_data.get("PurchaseOrderItemText"),
            MaterialType=item_data.get("MaterialType"),
            Material=material_id,
            MaterialName=material_info["name"],
            MaterialGroup=item_data.get("MaterialGroup"),
            SupplierCode=supplier_code,
            SupplierName=supplier_info["name"],
            CompanyCode=item_data.get("CompanyCode"),
            NetPriceAmount=net_price,
            NetPriceQuantity=net_price_qty,
            OrderQuantity=order_qty,
            DocumentCurrency=item_data.get("Currency") or item_data.get("DocumentCurrency", ""),
            CreationDate=creation_date,
            TotalCost=total_cost,
            TotalWeightKG=total_weight,
            EstimatedCO2kg=co2_impact
        )

    def get_product_order_items(
        self,
        secret_name: str,
        page_size: int = 1000,
    ) -> list[SAPProductOrderItem] | None:
        """
        Fetches all product order items from SAP OData and enriches them with sustainability data.
        """
        try:
            # base_url = "https://{host}:{port}/sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/purchaseorder/0001"

            # Get credentials from Secret Manager
            api_key = self.get_secret(secret_name)

            # Build URL with $expand to get CreationDate from the parent PurchaseOrder
            api_url = (
                f"{self.sandbox_url}/PurchaseOrderItem?%24top=50&%24expand=_PurchaseOrder"
            )

            headers = {
                "Accept": "application/json",
                "APIKey": f"{api_key}",
                "DataServiceVersion": "2.0"
            }

            # Call SAP OData
            response = requests.get(api_url, headers=headers, timeout=30)
            response.raise_for_status()  
            data = response.json()

            results = []
            value = data.get("value")

            if isinstance(value, list):
                for item in value:
                    try:
                        parent_po = item.get("_PurchaseOrder", {})
                        creation_date = parent_po.get("CreationDate", item.get("CreationDate", ""))
                        supplier_code = parent_po.get("SupplierCode", item.get("SupplierCode", ""))
                        
                        results.append(self._enrich_item(item, creation_date, supplier_code))
                    except Exception as parse_err:
                        print(f"WARNING: could not parse item: {parse_err}")
                        continue
            else:
                parent_po = data.get("_PurchaseOrder", {})
                creation_date = parent_po.get("CreationDate", data.get("CreationDate", ""))
                supplier_code = parent_po.get("SupplierCode", data.get("SupplierCode", ""))
                results.append(self._enrich_item(data, creation_date, supplier_code))

            return results

        except Exception as e:
            print(f"Error fetching SAP product order items: {e}")
            return None

if __name__ == "__main__":
    sap_client = SAPClient("dash-beta-e61d0")
    print(sap_client.get_product_order_items("CORZZX0MxTQtGyAD7PSCI1HLp3y2_SAP_key", page_size=25))