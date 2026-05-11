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
    """Standardized model for SAP product order item data with sustainability enrichment."""
    PurchaseOrder: str
    PurchaseOrderItem: str
    PurchaseOrderItemText: str
    MaterialType: str
    Material: str
    MaterialName: str = "Unknown Material"  # Enriched
    MaterialGroup: str
    SupplierCode: str                       # From SAP
    SupplierName: str = "Unknown Supplier"  # Enriched
    CompanyCode: str
    NetPriceAmount: float
    NetPriceQuantity: int
    OrderQuantity: int
    DocumentCurrency: str
    CreationDate: str
    
    # Calculated Fields
    TotalCost: float = 0.0
    TotalWeightKG: float = 0.0
    EstimatedCO2kg: float = 0.0

    def to_metadata(self):
        """Convert to the flat dictionary format used for GCS blob metadata."""
        return {
            "PurchaseOrder": self.PurchaseOrder,
            "PurchaseOrderItem": self.PurchaseOrderItem,    
            "PurchaseOrderItemText": self.PurchaseOrderItemText,
            "Material": self.Material,
            "MaterialName": self.MaterialName,
            "SupplierCode": self.SupplierCode,
            "SupplierName": self.SupplierName,
            "NetPriceAmount": str(self.NetPriceAmount),
            "OrderQuantity": str(self.OrderQuantity),
            "Currency": self.DocumentCurrency,
            "TotalCost": f"{self.TotalCost:.2f}",
            "TotalWeightKG": f"{self.TotalWeightKG:.2f}",
            "EstimatedCO2kg": f"{self.EstimatedCO2kg:.2f}",
            "CreationDate": self.CreationDate
        }
