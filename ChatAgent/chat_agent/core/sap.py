import requests
from datetime import datetime, timedelta
from google.cloud import secretmanager
from chat_agent.core.models import SAPProductOrderItem

class SAPClient:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.sandbox_url = "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata4/sap/api_purchaseorder_2/srvd_a2x/sap/purchaseorder/0001"

    def get_secret(self, secret_id: str) -> str:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{self.project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")

    def get_product_order_items(
        self,
        secret_name: str,
        page_size: int = 1000,
    ) -> list[SAPProductOrderItem] | None:
        """
        Fetches all product order items from SAP OData.

        Args:
            secret_name: Name of the Secret Manager secret containing SAP credentials
            page_size: Number of items to request per page (SAP default is often 25)

        Returns:
            List of SAPProductOrderItem instances (0-N items).
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
            response = requests.get(
                api_url,
                headers=headers,
                timeout=30
            )
            
            # Raise HTTPError for 4xx/5xx responses
            response.raise_for_status()  

            data = response.json()

            # Handle different shapes of SAP OData responses
            results = []
            value = data.get("value")

            if isinstance(value, list):
                # Standard OData 'value': list of items
                for item in value:
                    try:
                        # Extract CreationDate from the expanded parent PurchaseOrder object
                        parent_po = item.get("_PurchaseOrder", {})
                        creation_date = parent_po.get("CreationDate", item.get("CreationDate", ""))

                        parsed = SAPProductOrderItem(
                            PurchaseOrder=item.get("PurchaseOrder"),
                            PurchaseOrderItem=item.get("PurchaseOrderItem"),
                            PurchaseOrderItemText=item.get("PurchaseOrderItemText"),
                            MaterialType=item.get("MaterialType"),
                            Material=item.get("Material"),
                            MaterialGroup=item.get("MaterialGroup"),
                            CompanyCode=item.get("CompanyCode"),
                            NetPriceAmount=float(item.get("NetPriceAmount", 0)),
                            NetPriceQuantity=int(item.get("NetPriceQuantity", 0)),
                            OrderQuantity=int(item.get("OrderQuantity", 0)),
                            DocumentCurrency=item.get("Currency") or item.get("DocumentCurrency", ""),
                            CreationDate=creation_date,
                        )
                        results.append(parsed)
                    except (TypeError, ValueError, KeyError) as parse_err:
                        print(f"WARNING: could not parse item {item}: {parse_err}")
                        continue

            else:
                # If not a list, treat as single item
                try:
                    # Extract CreationDate from the expanded parent PurchaseOrder object
                    parent_po = data.get("_PurchaseOrder", {})
                    creation_date = parent_po.get("CreationDate", data.get("CreationDate", ""))

                    parsed = SAPProductOrderItem(
                        PurchaseOrder=data.get("PurchaseOrder"),
                        PurchaseOrderItem=data.get("PurchaseOrderItem"),
                        PurchaseOrderItemText=data.get("PurchaseOrderItemText"),
                        MaterialType=data.get("MaterialType"),
                        Material=data.get("Material"),
                        MaterialGroup=data.get("MaterialGroup"),
                        CompanyCode=data.get("CompanyCode"),
                        NetPriceAmount=float(data.get("NetPriceAmount", 0)),
                        NetPriceQuantity=int(data.get("NetPriceQuantity", 0)),
                        OrderQuantity=int(data.get("OrderQuantity", 0)),
                        DocumentCurrency=data.get("Currency") or data.get("DocumentCurrency", ""),
                        CreationDate=creation_date,
                    )
                    results.append(parsed)
                except (TypeError, ValueError, KeyError) as parse_err:
                    print(f"WARNING: could not parse single item: {parse_err}")
                    return None

            print(results[0].to_metadata())
            return results

        except Exception as e:
            print(f"Error fetching SAP product order items: {e}")
            return None

if __name__ == "__main__":
    sap_client = SAPClient("dash-beta-e61d0")
    sap_client.get_product_order_items("CORZZX0MxTQtGyAD7PSCI1HLp3y2_SAP_key", page_size=25)