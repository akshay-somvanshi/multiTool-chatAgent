from pydantic import BaseModel
from datetime import datetime

class EnergyConsumption(BaseModel):
    """Standardized model for energy consumption data from any provider."""
    user_id: str
    provider: str # e.g., 'Octopus', 'E.ON'
    consumption_kwh: float
    period_start: str # ISO format
    period_end: str   # ISO format
    meter_serial: str
    document_type: str = "api_consumption"
    mpan: str
    total_cost_gbp: float = 0.0

    def to_metadata(self):
        """Convert to the flat dictionary format used for GCS blob metadata."""
        return {
            "user_id": self.user_id,
            "provider": self.provider,
            "consumption_kwh": str(self.consumption_kwh),
            "total_cost_gbp": str(self.total_cost_gbp),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "document_type": self.document_type,
            "mpan": self.mpan
        }

class SAPProductOrderItem(BaseModel):
    """Standardized model for SAP product order item data from any provider."""
    PurchaseOrder: str
    PurchaseOrderItem: str
    PurchaseOrderItemText: str
    MaterialType: str
    Material: str
    MaterialGroup: str
    CompanyCode: str
    NetPriceAmount: float
    NetPriceQuantity: int
    OrderQuantity: int
    DocumentCurrency: str
    CreationDate: str

    def to_metadata(self):
        """Convert to the flat dictionary format used for GCS blob metadata."""
        return {
            "PurchaseOrder": self.PurchaseOrder,
            "PurchaseOrderItem": self.PurchaseOrderItem,    
            "PurchaseOrderItemText": self.PurchaseOrderItemText,
            "MaterialType": self.MaterialType,
            "Material": self.Material,
            "MaterialGroup": self.MaterialGroup,
            "CompanyCode": self.CompanyCode,
            "NetPriceAmount": str(self.NetPriceAmount),
            "NetPriceQuantity": str(self.NetPriceQuantity),
            "OrderQuantity": str(self.OrderQuantity),
            "Currency": self.DocumentCurrency,
            "CreationDate": self.CreationDate
        }
