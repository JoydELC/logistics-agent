"""
Orquestador principal del agente: clasificación, ejecución de herramientas y respuesta.
"""

import time
from pathlib import Path

import yaml

try:
    from api.utils.logger import get_logger
except ImportError:
    import logging
    get_logger = logging.getLogger

from agent.intent_classifier import IntentClassifier
from agent.response_builder import ResponseBuilder
from agent.tool_executor import ToolExecutor

logger = get_logger(__name__)
MAX_HISTORY_MESSAGES = 10

# Saludos que activan respuesta directa sin llamar a Ollama (evita timeout)
GREETING_PHRASES = frozenset({
    "hola", "hi", "hello", "hey", "buenos días", "buenas tardes", "buenas noches",
    "buenas", "good morning", "good afternoon", "good evening", "good day",
})


def _is_greeting_only(message: str) -> bool:
    """True si el mensaje es solo un saludo corto (palabras en GREETING_PHRASES o frase muy corta)."""
    text = (message or "").strip().lower()
    if not text or len(text) > 80:
        return False
    words = [w.strip(".,!?") for w in text.split() if w.strip()]
    if not words:
        return False
    if len(words) == 1 and words[0] in GREETING_PHRASES:
        return True
    if len(words) <= 3 and all(w in GREETING_PHRASES for w in words):
        return True
    # "Hola, buenos días" / "Hi there"
    if len(words) <= 4 and any(w in GREETING_PHRASES for w in words):
        rest = [w for w in words if w not in GREETING_PHRASES and len(w) > 1]
        if not rest or all(w in ("there", "todo", "bien", "ok") for w in rest):
            return True
    return False


def _greeting_response(client_config: dict) -> dict:
    """Respuesta de presentación usando message_formats.greeting del config."""
    formats = (client_config or {}).get("message_formats") or {}
    template = formats.get("greeting", "")
    client_name = (client_config or {}).get("client_name", "")
    if template and "{client_name}" in template:
        user_message = template.replace("{client_name}", client_name)
    else:
        lang = (client_config or {}).get("language", "es")
        if isinstance(lang, str) and lang.strip().lower() == "en":
            user_message = "Hello! I'm the assistant. How can I help you today?"
        else:
            user_message = "Buen día. Soy el asistente virtual. ¿En qué puedo ayudarle?"
    return {
        "intent": "other",
        "confidence": 1.0,
        "missing_fields": [],
        "tool": {"name": "none", "args": {}},
        "user_message": user_message,
    }


def _user_message_wrong_language(user_message: str, client_config: dict) -> bool:
    """Heurística simple: True si el mensaje parece estar en idioma distinto a config.language."""
    if not user_message or not user_message.strip():
        return False
    lang = (client_config or {}).get("language", "es")
    is_en = isinstance(lang, str) and lang.strip().lower() == "en"
    text = user_message.strip().lower()
    # Español: caracteres típicos o palabras frecuentes
    spanish_marks = "áéíóúñ" in text or " qué " in text or " cómo " in text or " necesito " in text or " envío " in text or " por favor " in text or " indicar " in text
    # Inglés: palabras típicas
    english_marks = " the " in text or " and " in text or " to " in text or " please " in text or " could you " in text or " provide " in text or " shipment " in text
    if is_en and spanish_marks and not english_marks:
        return True
    if not is_en and english_marks and not spanish_marks:
        return True
    return False


def _rewrite_user_message_with_templates(
    missing_fields: list,
    intent: str,
    client_config: dict,
) -> str:
    """Reescribe user_message usando plantillas del config en el idioma correcto (guardrail)."""
    formats = (client_config or {}).get("message_formats") or {}
    lang = (client_config or {}).get("language", "es")
    is_en = isinstance(lang, str) and lang.strip().lower() == "en"
    parts = [formats.get("ask_missing") or ("I need a few more details to help you out:" if is_en else "Para procesar su solicitud necesito la siguiente información:")]
    to_ask = list(missing_fields)[:2]
    if "shipment_id" in to_ask:
        parts.append("Shipment or package ID." if is_en else "Número o ID del envío.")
    if "new_date" in to_ask:
        parts.append(formats.get("ask_date_format") or ("New date in YYYY-MM-DD format." if is_en else "Nueva fecha en formato AAAA-MM-DD."))
    if "new_time_window" in to_ask:
        parts.append(formats.get("ask_time_window_format") or ("Morning, afternoon, evening or HH:MM-HH:MM." if is_en else "Mañana, tarde, noche o HH:MM-HH:MM."))
    if "issue_type" in to_ask:
        parts.append("Issue type: damage, delay, loss or other." if is_en else "Tipo: damage, delay, loss u other.")
    if "description" in to_ask:
        parts.append("Short description (min 5 characters)." if is_en else "Descripción breve (mín 5 caracteres).")
    if "severity" in to_ask:
        parts.append("Severity: low, medium, high." if is_en else "Severidad: low, medium, high.")
    if "contact_name" in to_ask:
        parts.append("Contact name." if is_en else "Nombre de contacto.")
    return " ".join(parts)


class AgentOrchestrator:
    """
    Orquesta el flujo: clasificar intención → ejecutar herramienta (si aplica)
    → construir respuesta final con ResponseBuilder o con la del classifier.
    """

    def __init__(
        self,
        client_config_path: str,
        ollama_url: str = "http://localhost:11434",
        api_url: str = "http://localhost:8000",
        model: str = "qwen2.5:7b",
    ) -> None:
        """
        Carga la config del cliente (YAML), inicializa classifier, tool_executor
        y response_builder. conversation_history vacío.
        """
        path = Path(client_config_path)
        if not path.is_file():
            raise FileNotFoundError(f"Config no encontrado: {client_config_path}")
        with open(path, encoding="utf-8") as f:
            self.client_config = yaml.safe_load(f) or {}
        self.client_name = self.client_config.get("client_name", "unknown")
        self.classifier = IntentClassifier(ollama_base_url=ollama_url, model=model)
        self.tool_executor = ToolExecutor(api_base_url=api_url)
        self.response_builder = ResponseBuilder(ollama_base_url=ollama_url, model=model)
        self.conversation_history: list[dict] = []
        # Contexto pendiente para multi-turn (reschedule/status/ticket)
        self._pending_intent: str | None = None
        self._pending_args: dict = {}
        logger.info("Orchestrator initialized for client: %s", self.client_name)

    def _trim_history(self) -> None:
        """Mantiene solo los últimos MAX_HISTORY_MESSAGES mensajes."""
        if len(self.conversation_history) > MAX_HISTORY_MESSAGES:
            self.conversation_history = self.conversation_history[-MAX_HISTORY_MESSAGES:]

    def _merge_pending_context(self, result: dict, user_message: str) -> dict:
        """Si hay un intent pendiente de turno anterior, fusionar campos nuevos."""
        if not self._pending_intent:
            # Guardar intent actual si tiene missing_fields
            if result.get("missing_fields"):
                self._pending_intent = result.get("intent")
                self._pending_args = (result.get("tool") or {}).get("args") or {}
            return result

        # Hay intent pendiente — el usuario probablemente está dando datos faltantes
        current_intent = result.get("intent", "other")
        current_args = (result.get("tool") or {}).get("args") or {}

        # Si el usuario cambió de tema explícitamente (nuevo intent fuerte), resetear
        if current_intent not in ("other", self._pending_intent):
            self._pending_intent = None
            self._pending_args = {}
            return result

        # Fusionar: mantener args pendientes, agregar nuevos no vacíos
        merged = dict(self._pending_args)
        for k, v in current_args.items():
            if v and str(v).strip():
                merged[k] = v

        # También intentar extraer del texto directamente
        from agent.intent_classifier import (
            _extract_shipment_id,
            _extract_new_date,
            _extract_new_time_window,
            _build_deterministic_response,
        )

        lang = (self.client_config or {}).get("language", "es")
        if not merged.get("shipment_id"):
            sid = _extract_shipment_id(user_message)
            if sid:
                merged["shipment_id"] = sid
        if self._pending_intent == "reschedule":
            if not merged.get("new_date"):
                d = _extract_new_date(user_message)
                if d:
                    merged["new_date"] = d
            if not merged.get("new_time_window"):
                tw = _extract_new_time_window(user_message, lang)
                if tw:
                    merged["new_time_window"] = tw

        result["intent"] = self._pending_intent
        result["tool"] = result.get("tool") or {"name": "none", "args": {}}
        result["tool"]["args"] = merged

        # Recalcular missing
        if self._pending_intent == "reschedule":
            needed = ["shipment_id", "new_date", "new_time_window"]
            missing = [f for f in needed if not merged.get(f)]
            result["missing_fields"] = missing
            if not missing:
                result["tool"]["name"] = "reschedule_shipment"
                merged.setdefault("note", "")
                self._pending_intent = None
                self._pending_args = {}
            else:
                result["tool"]["name"] = "none"
                self._pending_args = merged
        elif self._pending_intent == "status":
            if merged.get("shipment_id"):
                result["missing_fields"] = []
                result["tool"]["name"] = "get_shipment"
                self._pending_intent = None
                self._pending_args = {}
        elif self._pending_intent == "ticket":
            needed = ["shipment_id", "issue_type", "description", "severity"]
            missing = [f for f in needed if not merged.get(f)]
            result["missing_fields"] = missing
            if not missing:
                result["tool"]["name"] = "create_ticket"
                self._pending_intent = None
                self._pending_args = {}
            else:
                result["tool"]["name"] = "none"
                self._pending_args = merged

        # Reescribir user_message si aún faltan campos
        if result.get("missing_fields"):
            det = _build_deterministic_response(
                result["intent"],
                result["missing_fields"],
                "none",
                merged,
                self.client_config,
            )
            result["user_message"] = det["user_message"]

        return result

    async def process_message(self, user_message: str) -> dict:
        """
        Flujo principal: clasificar → si hay herramienta y no faltan campos, ejecutar
        y construir respuesta con ResponseBuilder; si no, devolver la respuesta del classifier.
        Actualiza el historial y lo limita a los últimos 10 mensajes.
        """
        if not (user_message and user_message.strip()):
            lang = (self.client_config or {}).get("language", "es")
            empty_msg = "I didn't receive any message. How can I help?" if (isinstance(lang, str) and lang.strip().lower() == "en") else "No recibí ningún mensaje. ¿En qué puedo ayudarle?"
            return {
                "intent": "other",
                "confidence": 0.0,
                "missing_fields": [],
                "tool": {"name": "none", "args": {}},
                "user_message": empty_msg,
            }

        # Saludo corto (hola/hi): respuesta directa desde config, sin llamar a Ollama
        if _is_greeting_only(user_message):
            result = _greeting_response(self.client_config)
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": result.get("user_message", "")})
            self._trim_history()
            return result

        try:
            result = self.classifier.classify(
                user_message,
                self.client_config,
                self.conversation_history,
            )
        except Exception as e:
            logger.exception("Error al clasificar: %s", e)
            from agent.intent_classifier import get_fallback_response
            return get_fallback_response(self.client_config)

        # Fusionar contexto pendiente multi-turn (si aplica)
        result = self._merge_pending_context(result, user_message)

        tool_name = (result.get("tool") or {}).get("name", "none")
        missing = result.get("missing_fields") or []

        if tool_name != "none" and not missing:
            t0 = time.perf_counter()
            try:
                tool_result = await self.tool_executor.execute(
                    tool_name,
                    (result.get("tool") or {}).get("args") or {},
                )
            except Exception as e:
                logger.exception("Error al ejecutar herramienta: %s", e)
                tool_result = {
                    "success": False,
                    "error": "No se pudo conectar con el servicio. Intente más tarde.",
                    "status_code": 503,
                }
            duration_ms = (time.perf_counter() - t0) * 1000

            try:
                final_response = self.response_builder.build(
                    tool_result=tool_result,
                    intent=result.get("intent", "other"),
                    client_config=self.client_config,
                )
            except Exception as e:
                logger.exception("Error al construir respuesta: %s", e)
                final_response = self.response_builder._fallback_from_tool_result(
                    tool_result,
                    result.get("intent", "other"),
                    self.client_config,
                )

            final_response["meta"] = {"tool_result": tool_result, "duration_ms": round(duration_ms, 2)}
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": final_response.get("user_message", "")})
            self._trim_history()
            return final_response
        else:
            # Guardrail: si user_message está en idioma incorrecto, reescribir con plantillas del config
            out_msg = result.get("user_message", "")
            if _user_message_wrong_language(out_msg, self.client_config):
                out_msg = _rewrite_user_message_with_templates(
                    result.get("missing_fields") or [],
                    result.get("intent", "other"),
                    self.client_config,
                )
                result = {**result, "user_message": out_msg}
            # Guardar intent pendiente si aún faltan campos
            if missing:
                self._pending_intent = result.get("intent")
                self._pending_args = (result.get("tool") or {}).get("args") or {}
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": result.get("user_message", "")})
            self._trim_history()
            return result

    def reset_conversation(self) -> None:
        """Limpia el historial de conversación."""
        self.conversation_history = []
        self._pending_intent = None
        self._pending_args = {}
        logger.info("Conversation reset for client: %s", self.client_name)

    def get_conversation_history(self) -> list:
        """Retorna el historial actual (lista de {role, content})."""
        return list(self.conversation_history)
