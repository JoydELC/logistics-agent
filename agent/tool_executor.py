"""
Ejecutor de herramientas: mapea tool_name a llamadas HTTP al Mock API.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)
TIMEOUT = 10.0


class ToolExecutor:
    """
    Ejecuta las herramientas get_shipment, reschedule_shipment, create_ticket
    contra la API local (FastAPI).
    """

    def __init__(self, api_base_url: str = "http://localhost:8000") -> None:
        self.api_base_url = api_base_url.rstrip("/")

    async def execute(self, tool_name: str, args: dict) -> dict:
        """
        Ejecuta la herramienta indicada y retorna
        {"success": True, "data": ...} o {"success": False, "error": str, "status_code": int?}.
        """
        if not tool_name or tool_name == "none":
            return {"success": True, "data": None, "message": "No tool needed"}

        start = time.perf_counter()
        try:
            if tool_name == "get_shipment":
                result = await self._get_shipment(args)
            elif tool_name == "reschedule_shipment":
                result = await self._reschedule_shipment(args)
            elif tool_name == "create_ticket":
                result = await self._create_ticket(args)
            else:
                return {"success": True, "data": None, "message": "No tool needed"}
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.warning("tool=%s error=%s duration_ms=%.0f", tool_name, e, duration_ms)
            return {"success": False, "error": "API no disponible", "status_code": 503}
        else:
            duration_ms = (time.perf_counter() - start) * 1000
            status = result.get("status_code") or (200 if result.get("success") else 500)
            logger.info(
                "tool=%s args_keys=%s status_code=%s duration_ms=%.0f",
                tool_name,
                list(args.keys()) if args else [],
                status,
                duration_ms,
            )
            return result

    async def _get_shipment(self, args: dict) -> dict:
        shipment_id = args.get("shipment_id")
        if not shipment_id:
            return {"success": False, "error": "shipment_id requerido", "status_code": 400}
        url = f"{self.api_base_url}/shipments/{shipment_id}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return {"success": True, "data": response.json()}
                return {
                    "success": False,
                    "error": response.text or f"HTTP {response.status_code}",
                    "status_code": response.status_code,
                }
        except httpx.ConnectError:
            return {"success": False, "error": "API no disponible", "status_code": 503}
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 503}

    async def _reschedule_shipment(self, args: dict) -> dict:
        shipment_id = args.get("shipment_id")
        if not shipment_id:
            return {"success": False, "error": "shipment_id requerido"}
        url = f"{self.api_base_url}/shipments/{shipment_id}/reschedule"
        body = {
            "new_date": args.get("new_date", ""),
            "new_time_window": args.get("new_time_window", ""),
            "note": args.get("note", ""),
        }
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(url, json=body)
                if response.status_code == 200:
                    return {"success": True, "data": response.json(), "status_code": 200}
                return {
                    "success": False,
                    "error": response.text or f"HTTP {response.status_code}",
                    "status_code": response.status_code,
                }
        except httpx.ConnectError:
            return {"success": False, "error": "API no disponible", "status_code": 503}
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 503}

    async def _create_ticket(self, args: dict) -> dict:
        url = f"{self.api_base_url}/tickets"
        # El body es args tal cual (shipment_id, issue_type, description, severity, contact)
        body = {k: v for k, v in args.items() if v is not None}
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.post(url, json=body)
                if response.status_code in (200, 201):
                    return {"success": True, "data": response.json(), "status_code": response.status_code}
                return {
                    "success": False,
                    "error": response.text or f"HTTP {response.status_code}",
                    "status_code": response.status_code,
                }
        except httpx.ConnectError:
            return {"success": False, "error": "API no disponible", "status_code": 503}
        except Exception as e:
            return {"success": False, "error": str(e), "status_code": 503}
