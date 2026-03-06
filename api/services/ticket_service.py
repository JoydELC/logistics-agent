"""
Servicio de tickets de incidencias. Almacena tickets en memoria.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from api.models.ticket import TicketCreate, TicketResponse

logger = logging.getLogger(__name__)


class TicketService:
    """
    Servicio de tickets en memoria.
    Lista de tickets sin persistencia a disco (MVP).
    """

    def __init__(self) -> None:
        """Inicializa la lista vacía de tickets."""
        self._tickets: list[TicketResponse] = []

    def count_tickets(self) -> int:
        """Cantidad de tickets en memoria (para health/startup)."""
        return len(self._tickets)

    def create_ticket(self, ticket_data: TicketCreate) -> TicketResponse:
        """
        Crea un ticket, genera ticket_id (TKT-{8 chars}), timestamp ISO,
        lo almacena y retorna el TicketResponse.
        """
        ticket_id = f"TKT-{uuid4().hex[:8].upper()}"
        created_at = datetime.now(timezone.utc).isoformat()

        response = TicketResponse(
            ticket_id=ticket_id,
            shipment_id=ticket_data.shipment_id,
            issue_type=ticket_data.issue_type,
            description=ticket_data.description,
            severity=ticket_data.severity,
            contact=ticket_data.contact,
            created_at=created_at,
            status="open",
        )
        self._tickets.append(response)
        logger.info(
            "Created ticket %s for shipment %s",
            ticket_id,
            ticket_data.shipment_id,
        )
        return response

    def get_tickets(self, shipment_id: Optional[str] = None) -> list[TicketResponse]:
        """
        Lista tickets. Si se pasa shipment_id, filtra por ese envío.
        Si no, retorna todos.
        """
        if shipment_id is None or shipment_id == "":
            return list(self._tickets)
        return [t for t in self._tickets if t.shipment_id == shipment_id]

    def get_ticket_by_id(self, ticket_id: str) -> Optional[TicketResponse]:
        """Obtiene un ticket por su ticket_id. Retorna None si no existe."""
        for t in self._tickets:
            if t.ticket_id == ticket_id:
                return t
        return None
