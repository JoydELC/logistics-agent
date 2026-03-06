"""
Rutas FastAPI para tickets de incidencias.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api.models.ticket import TicketCreate, TicketResponse
from api.services.ticket_service import TicketService
from api.utils.metrics import get_metrics_collector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["Tickets"])

_ticket_service: Optional[TicketService] = None


def get_ticket_service() -> TicketService:
    """Dependencia que devuelve la instancia única de TicketService."""
    global _ticket_service
    if _ticket_service is None:
        _ticket_service = TicketService()
    return _ticket_service


@router.post(
    "",
    response_model=TicketResponse,
    response_model_exclude_none=True,
    status_code=201,
    summary="Crear ticket",
    description="Crea un ticket de incidencia asociado a un envío. Valida issue_type (damage, delay, loss, other) y el resto de campos.",
)
def create_ticket(
    body: TicketCreate,
    service: TicketService = Depends(get_ticket_service),
) -> TicketResponse:
    """
    Crea un nuevo ticket con **shipment_id**, **issue_type**, **description** (mín. 5 caracteres),
    **severity** (low/medium/high) y **contact**. El ticket_id y created_at se generan automáticamente.
    """
    logger.info("Creating ticket for shipment %s", body.shipment_id)
    ticket = service.create_ticket(body)
    get_metrics_collector().record_ticket_created()
    logger.info("Created ticket %s for shipment %s", ticket.ticket_id, ticket.shipment_id)
    return ticket


@router.get(
    "",
    response_model=list[TicketResponse],
    response_model_exclude_none=True,
    summary="Listar tickets (BONUS)",
    description="Lista todos los tickets. Opcionalmente filtra por shipment_id mediante query param.",
)
def list_tickets(
    shipment_id: Optional[str] = None,
    service: TicketService = Depends(get_ticket_service),
) -> list[TicketResponse]:
    """
    **BONUS – Listado de tickets.**

    Si se envía **shipment_id** como query param, devuelve solo los tickets de ese envío.
    Si no, devuelve todos los tickets creados.
    """
    return service.get_tickets(shipment_id=shipment_id)


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    response_model_exclude_none=True,
    summary="Obtener ticket por ID (BONUS)",
    description="Devuelve un ticket por su ticket_id.",
)
def get_ticket(
    ticket_id: str,
    service: TicketService = Depends(get_ticket_service),
) -> TicketResponse:
    """
    **BONUS – Detalle de un ticket.**

    Obtiene el ticket con el **ticket_id** indicado. Responde 404 si no existe.
    """
    ticket = service.get_ticket_by_id(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Ticket not found", "ticket_id": ticket_id},
        )
    return ticket
