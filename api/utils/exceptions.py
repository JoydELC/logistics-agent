"""
Excepciones de aplicación con status_code y detail para respuestas HTTP consistentes.
"""

from datetime import datetime, timezone


class AppException(Exception):
    """Base para excepciones que se traducen a respuesta JSON con status_code."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail if detail is not None else message

    def to_dict(self) -> dict:
        """Dict para respuesta JSON consistente."""
        return {
            "error": self.message,
            "detail": self.detail,
            "status_code": self.status_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class ShipmentNotFoundError(AppException):
    """El envío con el ID indicado no existe."""

    def __init__(self, shipment_id: str) -> None:
        self.shipment_id = shipment_id
        super().__init__(
            message="Shipment not found",
            status_code=404,
            detail=f"No se encontró el envío con ID: {shipment_id}",
        )


class InvalidShipmentIdError(AppException):
    """El shipment_id no es válido (vacío o caracteres no permitidos)."""

    def __init__(self, shipment_id: str, reason: str) -> None:
        self.shipment_id = shipment_id
        super().__init__(
            message="Invalid shipment_id",
            status_code=400,
            detail=reason,
        )


class RescheduleNotAllowedError(AppException):
    """No se puede reprogramar el envío (ej. estado no permitido)."""

    def __init__(self, shipment_id: str, reason: str) -> None:
        self.shipment_id = shipment_id
        super().__init__(
            message="Reschedule not allowed",
            status_code=400,
            detail=reason,
        )


class ShipmentDataLoadError(AppException):
    """Error al cargar o validar el archivo de datos de envíos."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(
            message=message,
            status_code=503,
            detail=detail or message,
        )
