"""
Exportación de todos los modelos Pydantic del API.
"""

from .shipment import (
    FaxDetail,
    RescheduleRequest,
    RescheduleResponse,
    ShipmentListResponse,
    ShipmentRecord,
    ShipmentResponse,
)
from .ticket import (
    ContactInfo,
    TicketCreate,
    TicketResponse,
)

__all__ = [
    "FaxDetail",
    "ShipmentRecord",
    "ShipmentResponse",
    "ShipmentListResponse",
    "RescheduleRequest",
    "RescheduleResponse",
    "ContactInfo",
    "TicketCreate",
    "TicketResponse",
]
