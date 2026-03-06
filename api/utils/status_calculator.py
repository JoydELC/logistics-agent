"""
Calculador de estado derivado para envíos.
El JSON original no tiene campo 'status'; se deriva de date1/date2 y fecha actual.
"""

from datetime import datetime
from typing import Any


def _parse_date(date_str: str) -> datetime | None:
    """Parsea fecha YYYY-MM-DD. Retorna None si vacío o inválido."""
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def calculate_derived_status(shipment_record: dict[str, Any]) -> dict[str, str]:
    """
    Deriva el estado y el ETA a partir del registro de envío (sin campo 'status' en origen).

    Lógica de status (comparando con fecha actual):
    - date1 vacío -> pending_schedule
    - date2 futuro -> scheduled
    - date1 futuro -> scheduled
    - date1 hoy -> in_transit
    - date1 pasado y date2 vacío -> in_transit
    - date1 pasado y date2 pasado -> delivered
    - resto -> in_transit

    eta_info según order_type:
    - PU: "Pickup programado: {date1} {time1}"
    - DE: "Entrega programada: {date1} {time1} - {date2} {time2}" (si date2 existe)
    - CT: "Cross-town: {date1}"

    Si las fechas vienen vacías o en formato inválido, devuelve status "unknown".
    Retorna {"derived_status": str, "eta_info": str}.
    """
    result: dict[str, str] = {"derived_status": "unknown", "eta_info": ""}
    try:
        fax = shipment_record.get("fax") or {}
        date1_str = (fax.get("date1") or "").strip()
        date2_str = (fax.get("date2") or "").strip()
        order_type = (fax.get("order_type") or "").strip().upper()
        time1 = (fax.get("time1") or "").strip()
        time2 = (fax.get("time2") or "").strip()

        now = datetime.now()
        today = now.date()

        date1 = _parse_date(date1_str)
        date2 = _parse_date(date2_str)

        # --- derived_status ---
        if not date1_str:
            result["derived_status"] = "pending_schedule"
        elif date2 and date2.date() > today:
            result["derived_status"] = "scheduled"
        elif date1 and date1.date() > today:
            result["derived_status"] = "scheduled"
        elif date1 and date1.date() == today:
            result["derived_status"] = "in_transit"
        elif date1 and date1.date() < today and not date2_str:
            result["derived_status"] = "in_transit"
        elif date1 and date2 and date1.date() < today and date2.date() < today:
            result["derived_status"] = "delivered"
        elif date1 and date1.date() < today:
            result["derived_status"] = "in_transit"
        else:
            result["derived_status"] = "unknown"

        # --- eta_info ---
        if order_type == "PU":
            result["eta_info"] = f"Pickup programado: {date1_str} {time1}".strip()
        elif order_type == "DE":
            if date2_str:
                result["eta_info"] = (
                    f"Entrega programada: {date1_str} {time1} - {date2_str} {time2}".strip()
                )
            else:
                result["eta_info"] = f"Entrega programada: {date1_str} {time1}".strip()
        elif order_type == "CT":
            result["eta_info"] = f"Cross-town: {date1_str}".strip()
        else:
            result["eta_info"] = f"{date1_str} {time1}".strip() if date1_str else ""

    except Exception:
        result["derived_status"] = "unknown"
        result["eta_info"] = ""

    return result
