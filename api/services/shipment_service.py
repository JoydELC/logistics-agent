"""
Servicio de envíos: carga en memoria, búsqueda por ID y reprogramación.
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

from api.utils.exceptions import ShipmentDataLoadError
from api.utils.status_calculator import calculate_derived_status

logger = logging.getLogger(__name__)

# Ventanas horarias predefinidas: (time1, time2)
TIME_WINDOW_MAP = {
    "mañana": ("06:00", "12:00"),
    "tarde": ("12:00", "18:00"),
    "noche": ("18:00", "23:59"),
}


def _parse_time_window(value: str) -> tuple[str, str]:
    """
    Convierte new_time_window en (time1, time2).
    Acepta "mañana"|"tarde"|"noche" o "HH:MM-HH:MM".
    """
    normalized = (value or "").strip().lower()
    if normalized in TIME_WINDOW_MAP:
        return TIME_WINDOW_MAP[normalized]
    if "-" in value:
        parts = value.strip().split("-", 1)
        if len(parts) == 2:
            return (parts[0].strip(), parts[1].strip())
    return ("", "")


def _strip_mongo_id(record: dict[str, Any]) -> dict[str, Any]:
    """Quita _id del dict para que Pydantic (extra=forbid) no falle."""
    out = dict(record)
    out.pop("_id", None)
    return out


class ShipmentService:
    """
    Servicio de envíos con datos en memoria.
    Carga data/shipments.json al iniciar y mantiene un índice por shipmentid.
    """

    def __init__(self, data_path: Optional[Path] = None) -> None:
        """
        Carga el JSON de envíos en memoria y construye el índice por shipmentid.
        """
        if data_path is None:
            root = Path(__file__).resolve().parent.parent.parent
            data_path = root / "data" / "shipments.json"

        self._data_path = data_path
        self._records: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}

        self._load_data()

    def _load_data(self) -> None:
        """Carga el JSON y construye el índice {shipmentid: record}. Valida integridad."""
        try:
            with open(self._data_path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError as e:
            logger.error("Archivo de shipments no encontrado: %s", self._data_path)
            raise ShipmentDataLoadError(
                "Archivo de datos no encontrado",
                detail=f"No se encontró el archivo: {self._data_path}",
            ) from e
        except json.JSONDecodeError as e:
            logger.error("JSON de shipments corrupto: %s", e)
            raise ShipmentDataLoadError(
                "Archivo de datos corrupto",
                detail=f"El JSON no es válido: {e!s}",
            ) from e

        if not isinstance(raw, list):
            logger.error("El JSON de shipments debe ser una lista de registros")
            raise ShipmentDataLoadError(
                "Formato de datos inválido",
                detail="El archivo debe contener una lista de envíos",
            )

        self._records = []
        self._by_id = {}
        skipped = 0
        for record in raw:
            if not isinstance(record, dict):
                skipped += 1
                continue
            sid = record.get("shipmentid")
            if sid is None or str(sid).strip() == "":
                skipped += 1
                continue
            self._records.append(record)
            self._by_id[str(sid)] = record

        if skipped:
            logger.warning("Se omitieron %d registros sin shipmentid válido", skipped)
        logger.info(
            "Shipments cargados: %d registros, índice por shipmentid listo",
            len(self._records),
        )

    def count_shipments(self) -> int:
        """Cantidad de envíos cargados (para health/startup)."""
        return len(self._records)

    def get_shipment(self, shipment_id: str) -> Optional[dict[str, Any]]:
        """
        Busca un envío por ID. Si existe, aplica calculate_derived_status
        y retorna el registro enriquecido (sin _id). Si no existe, retorna None.
        """
        record = self._by_id.get(shipment_id)
        if record is None:
            logger.warning("Shipment no encontrado: shipment_id=%s", shipment_id)
            return None

        enriched = dict(record)
        status_info = calculate_derived_status(record)
        enriched["derived_status"] = status_info["derived_status"]
        enriched["eta_info"] = status_info["eta_info"]
        logger.info(
            "Shipment obtenido: shipment_id=%s, derived_status=%s",
            shipment_id,
            status_info["derived_status"],
        )
        return _strip_mongo_id(enriched)

    def reschedule_shipment(
        self,
        shipment_id: str,
        new_date: str,
        new_time_window: str,
        note: str = "",
    ) -> dict[str, Any]:
        """
        Reprograma un envío: actualiza date1 y time1/time2 según new_date y new_time_window.
        La data se muta en memoria; no se persiste a disco.
        Retorna un dict con success, shipment_id, previous_date, new_date, new_time_window, message.
        Si el envío no existe, retorna success=False y message="Shipment not found".
        """
        record = self._by_id.get(shipment_id)
        if record is None:
            logger.warning(
                "Reschedule fallido: shipment no encontrado, shipment_id=%s",
                shipment_id,
            )
            return {
                "success": False,
                "shipment_id": shipment_id,
                "previous_date": None,
                "new_date": new_date,
                "new_time_window": new_time_window,
                "message": "Shipment not found",
            }

        fax = record.get("fax")
        if not isinstance(fax, dict):
            fax = {}
            record["fax"] = fax

        previous_date = (fax.get("date1") or "").strip() or None
        fax["date1"] = new_date.strip()
        time1, time2 = _parse_time_window(new_time_window)
        fax["time1"] = time1
        fax["time2"] = time2

        logger.info(
            "Reschedule OK: shipment_id=%s, previous_date=%s, new_date=%s, new_time_window=%s",
            shipment_id,
            previous_date,
            new_date,
            new_time_window,
        )
        return {
            "success": True,
            "shipment_id": shipment_id,
            "previous_date": previous_date,
            "new_date": new_date,
            "new_time_window": new_time_window,
            "message": "Reprogramación aplicada correctamente.",
        }

    def list_shipments(
        self,
        order_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Lista envíos con filtro opcional por order_type (PU/DE/CT) y paginación.
        Retorna (lista de registros enriquecidos sin _id, total_count).
        """
        filtered = self._records
        if order_type and order_type.strip().upper() in ("PU", "DE", "CT"):
            ot = order_type.strip().upper()
            filtered = [
                r for r in self._records
                if (r.get("fax") or {}).get("order_type") == ot
            ]
        total = len(filtered)
        slice_records = filtered[offset : offset + limit]
        items = []
        for record in slice_records:
            enriched = dict(record)
            status_info = calculate_derived_status(record)
            enriched["derived_status"] = status_info["derived_status"]
            enriched["eta_info"] = status_info["eta_info"]
            items.append(_strip_mongo_id(enriched))
        return (items, total)
