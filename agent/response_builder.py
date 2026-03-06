"""
Construye la respuesta final al usuario a partir del TOOL_RESULT usando el LLM.
"""

import json
from pathlib import Path

import httpx

try:
    from api.utils.logger import get_logger
except ImportError:
    import logging
    get_logger = logging.getLogger

logger = get_logger(__name__)

RESPONSE_FALLBACK = {
    "intent": "other",
    "confidence": 1.0,
    "missing_fields": [],
    "tool": {"name": "none", "args": {}},
    "user_message": "No pude generar una respuesta en este momento. Por favor, intente de nuevo.",
}


class ResponseBuilder:
    """
    Usa el prompt system_prompt_response.txt y Ollama para humanizar
    la respuesta basada en TOOL_RESULT. Si Ollama falla, construye un fallback.
    """

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
    ) -> None:
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model
        self._prompt_path = Path(__file__).resolve().parent / "prompts" / "system_prompt_response.txt"

    def _load_prompt(self, client_config: dict, tool_result: dict, intent: str) -> str:
        """Carga el prompt y reemplaza los placeholders."""
        try:
            text = self._prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("No se pudo cargar system_prompt_response.txt: %s", e)
            return ""
        config_json = json.dumps(client_config, ensure_ascii=False, indent=2)
        result_json = json.dumps(tool_result, ensure_ascii=False, indent=2)
        text = text.replace("{{CLIENT_CONFIG_JSON}}", config_json)
        text = text.replace("{{TOOL_RESULT_JSON}}", result_json)
        text = text.replace("{{INTENT}}", intent)
        return text

    def _fallback_from_tool_result(self, tool_result: dict, intent: str) -> dict:
        """Construye una respuesta básica sin LLM cuando Ollama falla."""
        success = tool_result.get("success", False)
        data = tool_result.get("data")
        error = tool_result.get("error", "")
        message = tool_result.get("message", "")

        if success and data:
            if intent == "status" and isinstance(data, dict):
                sid = data.get("shipmentid", "N/A")
                status = data.get("derived_status", "N/A")
                eta = data.get("eta_info", "")
                fax = data.get("fax") or {}
                order_type = fax.get("order_type", "N/A")
                origin = fax.get("stop1_name") or fax.get("stop1_city") or "no disponible"
                dest = fax.get("stop2_name") or fax.get("stop2_city") or "no disponible"
                user_message = f"Envío {sid}: tipo {order_type}, estado {status}. Origen: {origin}. Destino: {dest}. {eta}"
            elif intent == "reschedule" and isinstance(data, dict):
                sid = data.get("shipment_id", "N/A")
                new_date = data.get("new_date", "N/A")
                time_window = data.get("new_time_window", "N/A")
                user_message = f"Reprogramación confirmada. Envío {sid}: nueva fecha {new_date}, ventana {time_window}."
            elif intent == "ticket" and isinstance(data, dict):
                tid = data.get("ticket_id", "N/A")
                issue = data.get("issue_type", "N/A")
                sev = data.get("severity", "N/A")
                user_message = f"Ticket creado: {tid}. Tipo: {issue}, severidad: {sev}. Le daremos seguimiento."
            else:
                user_message = "Operación completada correctamente."
        else:
            user_message = f"No se pudo completar la operación. {error or message}".strip() or "Error desconocido. ¿Desea reintentar o hablar con un agente?"

        return {
            "intent": intent,
            "confidence": 1.0,
            "missing_fields": [],
            "tool": {"name": "none", "args": {}},
            "user_message": user_message,
        }

    def build(self, tool_result: dict, intent: str, client_config: dict) -> dict:
        """
        Genera la respuesta final usando Ollama y el prompt de response.
        Si Ollama falla, retorna un fallback construido del tool_result.
        """
        prompt = self._load_prompt(client_config, tool_result, intent)
        if not prompt:
            return self._fallback_from_tool_result(tool_result, intent)

        url = f"{self.ollama_base_url}/api/chat"
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Genera la respuesta en JSON con el formato indicado."},
        ]
        body = {"model": self.model, "messages": messages, "stream": False, "format": "json"}

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
        except (httpx.TimeoutException, httpx.HTTPError, Exception) as e:
            logger.warning("ResponseBuilder: Ollama no respondió: %s", e)
            return self._fallback_from_tool_result(tool_result, intent)

        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.warning("ResponseBuilder: respuesta de Ollama no es JSON")
            return self._fallback_from_tool_result(tool_result, intent)

        content = None
        if isinstance(data, dict):
            msg = data.get("message") or data.get("response")
            if isinstance(msg, dict):
                content = msg.get("content")
            elif isinstance(data.get("content"), str):
                content = data.get("content")

        if not content or not content.strip():
            logger.warning("ResponseBuilder: contenido vacío de Ollama")
            return self._fallback_from_tool_result(tool_result, intent)

        try:
            parsed = json.loads(content.strip())
        except json.JSONDecodeError:
            stripped = content.strip()
            if "{" in stripped:
                start = stripped.index("{")
                try:
                    parsed = json.loads(stripped[start:].split("```")[0].strip())
                except json.JSONDecodeError:
                    parsed = None
            else:
                parsed = None
            if not isinstance(parsed, dict) or "user_message" not in parsed:
                logger.warning("ResponseBuilder: no se pudo extraer JSON válido")
                return self._fallback_from_tool_result(tool_result, intent)

        if not isinstance(parsed.get("user_message"), str):
            return self._fallback_from_tool_result(tool_result, intent)

        # Asegurar formato completo
        return {
            "intent": parsed.get("intent", intent),
            "confidence": float(parsed.get("confidence", 1.0)),
            "missing_fields": parsed.get("missing_fields", []),
            "tool": parsed.get("tool", {"name": "none", "args": {}}),
            "user_message": parsed["user_message"],
        }
