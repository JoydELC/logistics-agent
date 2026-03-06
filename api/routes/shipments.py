"""
Rutas FastAPI para envíos (shipments).
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends

from api.models.shipment import (
    RescheduleRequest,
    RescheduleResponse,
    ShipmentListResponse,
    ShipmentResponse,
)
from api.services.shipment_service import ShipmentService
from api.utils.exceptions import (
    InvalidShipmentIdError,
    RescheduleNotAllowedError,
    ShipmentNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shipments", tags=["Shipments"])

# Solo alfanuméricos, guiones y espacios (evita inyección/caracteres peligrosos)
SHIPMENT_ID_REGEX = re.compile(r"^[a-zA-Z0-9\-\s]+$")


def _validate_shipment_id(shipment_id: str) -> None:
    """Valida shipment_id: no vacío y solo caracteres permitidos. Lanza InvalidShipmentIdError si falla."""
    if not shipment_id or not str(shipment_id).strip():
        raise InvalidShipmentIdError(
            shipment_id=shipment_id,
            reason="shipment_id no puede estar vacío",
        )
    if not SHIPMENT_ID_REGEX.match(shipment_id):
        raise InvalidShipmentIdError(
            shipment_id=shipment_id,
            reason="shipment_id solo puede contener letras, números, guiones y espacios",
        )

_shipment_service: Optional[ShipmentService] = None


def get_shipment_service() -> ShipmentService:
    """Dependencia que devuelve la instancia única de ShipmentService."""
    global _shipment_service
    if _shipment_service is None:
        _shipment_service = ShipmentService()
    return _shipment_service


@router.get(
    "",
    response_model=ShipmentListResponse,
    response_model_exclude_none=True,
    summary="Listar envíos",
    description="Lista todos los envíos con paginación y filtro opcional por tipo de orden (PU/DE/CT).",
)
def list_shipments(
    order_type: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentListResponse:
    """
    **BONUS – Listado paginado.**

    Parámetros de consulta opcionales:
    - **order_type**: Filtrar por tipo (PU, DE, CT).
    - **limit**: Máximo de registros a devolver (default 20).
    - **offset**: Registros a saltar para paginación (default 0).

    Devuelve la lista de envíos enriquecidos con derived_status y eta_info, y el total de registros.
    """
    items, total = service.list_shipments(order_type=order_type, limit=limit, offset=offset)
    return ShipmentListResponse(
        items=[ShipmentResponse.model_validate(r) for r in items],
        total=total,
    )


@router.get(
    "/{shipment_id}",
    response_model=ShipmentResponse,
    response_model_exclude_none=True,
    summary="Obtener envío por ID",
    description="Devuelve un envío por su shipment_id con estado derivado y ETA.",
)
def get_shipment(
    shipment_id: str,
    service: ShipmentService = Depends(get_shipment_service),
) -> ShipmentResponse:
    """
    Obtiene el detalle de un envío por **shipment_id**.
    Incluye el estado derivado (derived_status) y la información ETA (eta_info).
    """
    _validate_shipment_id(shipment_id)
    logger.info("Queried shipment %s", shipment_id)
    record = service.get_shipment(shipment_id)
    if record is None:
        raise ShipmentNotFoundError(shipment_id)
    return ShipmentResponse.model_validate(record)


@router.post(
    "/{shipment_id}/reschedule",
    response_model=RescheduleResponse,
    response_model_exclude_none=True,
    summary="Reprogramar envío",
    description="Reprograma la fecha y ventana horaria de un envío.",
)
def reschedule_shipment(
    shipment_id: str,
    body: RescheduleRequest,
    service: ShipmentService = Depends(get_shipment_service),
) -> RescheduleResponse:
    """
    Reprograma un envío indicando la nueva fecha (**new_date**, YYYY-MM-DD) y la ventana horaria
    (**new_time_window**: "mañana", "tarde", "noche" o "HH:MM-HH:MM"). Opcionalmente se puede enviar una **note**.
    """
    _validate_shipment_id(shipment_id)
    logger.info("Rescheduled shipment %s to %s", shipment_id, body.new_date)
    result = service.reschedule_shipment(
        shipment_id=shipment_id,
        new_date=body.new_date,
        new_time_window=body.new_time_window,
        note=body.note or "",
    )
    if not result["success"]:
        raise RescheduleNotAllowedError(shipment_id=shipment_id, reason=result["message"])
    return RescheduleResponse.model_validate(result)
