"""
Clasificador de intenciones: keyword-first determinístico + LLM como respaldo.
Evita alucinaciones: nunca inventa shipment_id, fechas ni horarios.
user_message SIEMPRE en config.language.
"""

import json
import logging
import re
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# Palabras clave por intención (match fuerte para pre-clasificador)
KEYWORDS_RESCHEDULE = frozenset({
    "reschedule", "reprogram", "change date", "new date", "delivery date",
    "reprogramar", "cambiar fecha", "cambiar día", "otra fecha", "cambiar entrega",
    "reagendar", "mover fecha", "reprogram", "reschedule",
})
KEYWORDS_STATUS = frozenset({
    "status", "state", "tracking", "where is", "where's", "how is my",
    "estado", "seguimiento", "dónde está", "cómo va", "ubicación", "consulta envío",
})
KEYWORDS_TICKET = frozenset({
    "damage", "damaged", "delay", "lost", "ticket", "incident", "report",
    "dañado", "retraso", "pérdida", "incidencia", "reportar", "problema",
})
GREETING_WORDS = frozenset({
    "hola", "hi", "hello", "hey", "buenos días", "buenas tardes", "buenas noches",
    "buenas", "good morning", "good afternoon", "good evening", "good day",
})

# Para detección "match fuerte": mensaje corto o frase que contiene solo/básicamente la keyword
def _text_normalize(msg: str) -> str:
    return (msg or "").strip().lower()

def _words(msg: str) -> list[str]:
    return re.findall(r"[a-záéíóúñ0-9]+", _text_normalize(msg))

REQUIRED_KEYS = {"intent", "confidence", "missing_fields", "tool", "user_message"}

# Valores de ventana horaria que acepta la API (siempre en español para el backend)
TIME_WINDOW_API_VALUES = {"mañana", "tarde", "noche"}
TIME_WINDOW_EN_TO_API = {"morning": "mañana", "afternoon": "tarde", "evening": "noche"}
TIME_WINDOW_ES = {"mañana", "tarde", "noche"}
# Patrón HH:MM-HH:MM
TIME_RANGE_PATTERN = re.compile(r"\b(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\b", re.I)
# Fecha YYYY-MM-DD (no inventar otras)
DATE_YYYY_MM_DD = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
# Posible shipment_id: alfanumérico y guiones (4-30 chars) o solo dígitos (3+ chars)
SHIPMENT_ID_PATTERN = re.compile(r"\b([A-Za-z0-9\-]{4,30})\b|\b(\d{3,})\b")

DEFAULT_REQUIRED = {
    "status": ["shipment_id"],
    "reschedule": ["shipment_id", "new_date", "new_time_window"],
    "ticket": ["shipment_id", "issue_type", "description", "severity", "contact_name"],
}


def _get_required_fields(client_config: dict, intent: str) -> list[str]:
    """Obtiene required_fields para la intención desde YAML o DEFAULT_REQUIRED."""
    rf = (client_config or {}).get("required_fields") or {}
    return list(rf.get(intent, DEFAULT_REQUIRED.get(intent, [])))


def _is_greeting_only(msg: str) -> bool:
    text = _text_normalize(msg)
    if not text or len(text) > 80:
        return False
    words = _words(msg)
    if not words:
        return False
    if len(words) == 1 and words[0] in GREETING_WORDS:
        return True
    if len(words) <= 3 and all(w in GREETING_WORDS for w in words):
        return True
    return False


def _keyword_suggested_intent(user_message: str) -> str | None:
    """Devuelve 'reschedule'|'status'|'ticket' si hay match con keywords, sino None."""
    text = _text_normalize(user_message)
    if not text:
        return None
    if any(k in text for k in KEYWORDS_RESCHEDULE):
        return "reschedule"
    if any(k in text for k in KEYWORDS_STATUS):
        return "status"
    if any(k in text for k in KEYWORDS_TICKET):
        return "ticket"
    return None


def _preclassify_deterministic(user_message: str) -> str | None:
    """
    Pre-clasificador por reglas. Retorna intent si hay un solo match fuerte, sino None.
    Si es saludo → other. Si hay conflicto (varias intenciones) → None (usar LLM).
    """
    if _is_greeting_only(user_message):
        return "other"
    text = _text_normalize(user_message)
    words = _words(user_message)
    matches = []
    if any(k in text for k in KEYWORDS_RESCHEDULE):
        matches.append("reschedule")
    if any(k in text for k in KEYWORDS_STATUS):
        matches.append("status")
    if any(k in text for k in KEYWORDS_TICKET):
        matches.append("ticket")
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return None  # Conflicto: LLM desempata
    return None


# --- Extracción de entidades (sin inventar) ---

def _extract_shipment_id(user_message: str) -> str | None:
    """Extrae un posible shipment_id si hay un token tipo ID. No inventa."""
    keywords_all = (
        KEYWORDS_RESCHEDULE | KEYWORDS_STATUS | KEYWORDS_TICKET | GREETING_WORDS
        | {
            # Palabras comunes que NUNCA deben ser shipment_id
            "shipment",
            "envio",
            "envío",
            "package",
            "packages",
            "paquete",
            "paquetes",
            "delivery",
            "deliver",
            "order",
            "orders",
            "pedido",
            "pedidos",
            "orden",
            "ordenes",
            "id",
            "numero",
            "number",
            "need",
            "want",
            "have",
            "with",
            "from",
            "para",
            "for",
            "the",
            "can",
            "could",
            "please",
            "to",
            "my",
            "your",
            "mi",
            "tu",
            "su",
            "el",
            "la",
            "los",
            "las",
            "del",
            "qué",
            "por",
            "estado",
            "está",
            "necesito",
            "reprogramar",
            "reagendar",
            "reschedule",
        }
    )
    for m in SHIPMENT_ID_PATTERN.finditer(user_message or ""):
        raw = m.group(1) or m.group(2) or ""
        if not raw:
            continue
        token = raw.lower()
        if token in keywords_all or len(token) < 3:
            continue
        # Solo dígitos: aceptar 3+ (ej. "123")
        if token.isdigit() and len(token) >= 3:
            return raw
        # Alfanumérico con al menos un dígito: patrón típico de ID (ABC123, A-1234, etc.)
        if len(raw) >= 4 and re.match(r"^[A-Za-z0-9\-]+$", raw) and any(c.isdigit() for c in raw):
            return raw
    return None


def _extract_new_date(user_message: str) -> str | None:
    """Solo acepta YYYY-MM-DD literal. Si dice tomorrow/lunes etc. retorna None."""
    match = DATE_YYYY_MM_DD.search(user_message or "")
    if match:
        return match.group(0)
    return None


def _extract_new_time_window(user_message: str, language: str) -> str | None:
    """
    Extrae ventana horaria. Valores aceptados: mañana|tarde|noche|HH:MM-HH:MM.
    Para API siempre devolvemos mañana|tarde|noche (español). Si usuario dice afternoon → "tarde".
    """
    text = _text_normalize(user_message)
    # Rango explícito
    range_m = TIME_RANGE_PATTERN.search(user_message or "")
    if range_m:
        return f"{range_m.group(1)}-{range_m.group(2)}"
    # ES
    for tw in TIME_WINDOW_ES:
        if tw in text:
            return tw
    # EN → normalizar a valor API
    for en, api in TIME_WINDOW_EN_TO_API.items():
        if en in text:
            return api
    return None


def _build_tool_name(intent: str, args: dict, required: list[str]) -> str:
    """Nombre de herramienta si tenemos todos los args necesarios para esa intención."""
    if intent == "other":
        return "none"
    if intent == "status":
        return "get_shipment" if args.get("shipment_id") else "none"
    if intent == "reschedule":
        if args.get("shipment_id") and args.get("new_date") and args.get("new_time_window"):
            return "reschedule_shipment"
        return "none"
    if intent == "ticket":
        # create_ticket requiere varios campos; simplificado: si tenemos los mínimos
        if args.get("shipment_id") and args.get("issue_type") and args.get("description") and args.get("severity") and args.get("contact"):
            return "create_ticket"
        return "none"
    return "none"


def _build_deterministic_response(
    intent: str,
    missing_fields: list[str],
    tool_name: str,
    tool_args: dict,
    client_config: dict,
) -> dict:
    """Construye user_message en idioma config.language pidiendo solo missing_fields (máx 2)."""
    lang = (client_config or {}).get("language", "es")
    is_en = isinstance(lang, str) and lang.strip().lower() == "en"
    formats = (client_config or {}).get("message_formats") or {}

    to_ask = missing_fields[:2]  # Máximo 2 preguntas por turno

    if intent == "other":
        greeting = formats.get("greeting", "")
        client_name = (client_config or {}).get("client_name", "")
        if greeting and "{client_name}" in greeting:
            user_message = greeting.replace("{client_name}", client_name)
        else:
            user_message = "Hello! How can I help?" if is_en else "Buen día. ¿En qué puedo ayudarle?"
        return {
            "intent": "other",
            "confidence": 1.0,
            "missing_fields": [],
            "tool": {"name": "none", "args": {}},
            "user_message": user_message,
        }

    parts = []
    if "shipment_id" in to_ask:
        if is_en:
            parts.append("To proceed I need the shipment or package ID. Could you provide it?")
        else:
            parts.append("Para continuar necesito el número o ID del envío. ¿Podría indicarlo?")
    if "new_date" in to_ask:
        parts.append(formats.get("ask_date_format") or ("Please provide the new date in YYYY-MM-DD format, e.g. 2025-03-15." if is_en else "Por favor indique la nueva fecha en formato AAAA-MM-DD, por ejemplo 2025-03-15."))
    if "new_time_window" in to_ask:
        parts.append(formats.get("ask_time_window_format") or ("You can choose: morning (6-12), afternoon (12-18), evening (18-24), or a range like 09:00-14:00." if is_en else "Puede elegir: mañana (6-12h), tarde (12-18h), noche (18-24h), o un rango como 09:00-14:00."))
    if "issue_type" in to_ask:
        parts.append("For issue type use: damage, delay, loss or other." if is_en else "Para el tipo de incidencia indique: damage, delay, loss u other.")
    if "description" in to_ask:
        parts.append("Please provide a short description (at least 5 characters)." if is_en else "Indique una descripción breve (mínimo 5 caracteres).")
    if "severity" in to_ask:
        parts.append("Severity: low, medium or high." if is_en else "Severidad: low, medium o high.")
    if "contact_name" in to_ask or "contact" in to_ask:
        parts.append("I need a contact name for the ticket." if is_en else "Necesito un nombre de contacto para el ticket.")

    user_message = " ".join(parts) if parts else (formats.get("ask_missing") or ("I need a few more details." if is_en else "Necesito algunos datos más."))

    return {
        "intent": intent,
        "confidence": 0.85,
        "missing_fields": missing_fields,
        "tool": {"name": tool_name, "args": tool_args},
        "user_message": user_message,
    }


def get_fallback_response(client_config: dict) -> dict:
    """Fallback cuando LLM falla. Idioma según config.language."""
    lang = (client_config or {}).get("language", "es")
    if isinstance(lang, str) and lang.strip().lower() == "en":
        msg = "Sorry, I couldn't process your request. Can you rephrase?"
    else:
        msg = "Lo siento, no pude procesar tu solicitud. ¿Puedes reformularla?"
    return {
        "intent": "other",
        "confidence": 0.0,
        "missing_fields": [],
        "tool": {"name": "none", "args": {}},
        "user_message": msg,
    }


def _retry_system_prompt(client_config: dict) -> str:
    """Prompt de retry con config.language inyectado: user_message SIEMPRE en ese idioma."""
    lang = (client_config or {}).get("language", "es")
    lang_instruction = "en" if (isinstance(lang, str) and lang.strip().lower() == "en") else "es"
    return f"""Classify the user message into exactly one intent: status, reschedule, ticket, or other.
Reply ONLY with valid JSON. No other text.
CRITICAL: The "user_message" field MUST be written entirely in {lang_instruction.upper()} (config.language). Do NOT use the user's language; use {lang_instruction} only.

Required JSON:
{{"intent": "status|reschedule|ticket|other", "confidence": 0.9, "missing_fields": [], "tool": {{"name": "get_shipment|reschedule_shipment|create_ticket|none", "args": {{}}}}, "user_message": "..."}}

- status: user wants shipment status/tracking. tool name get_shipment only if shipment_id is in the message; else none, missing_fields ["shipment_id"].
- reschedule: user wants to change delivery date. tool name reschedule_shipment only if shipment_id AND new_date (YYYY-MM-DD) AND new_time_window are all present; else none, missing_fields list what is missing (start with shipment_id if absent).
- ticket: user reports damage/delay/loss. tool name create_ticket or none, missing_fields as needed.
- other: greeting or unrelated. tool name none, missing_fields [].

Do NOT invent shipment_id, dates or times. user_message in {lang_instruction} only."""


class IntentClassifier:
    """
    Clasificación keyword-first: pre-clasificador determinístico, luego LLM solo si hay conflicto o sin match.
    Si LLM devuelve "other" pero keywords sugieren reschedule/status/ticket → override a esa intención y respuesta determinística.
    """

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
    ) -> None:
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model
        self._prompt_path = Path(__file__).resolve().parent / "prompts" / "system_prompt_classifier.txt"

    def _load_system_prompt(self, client_config: dict) -> str:
        try:
            text = self._prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("No se pudo cargar system_prompt_classifier.txt: %s", e)
            return ""
        config_json = json.dumps(client_config, ensure_ascii=False, indent=2)
        return text.replace("{{CLIENT_CONFIG_JSON}}", config_json)

    MAX_HISTORY_TURNS = 4

    def _messages(self, system_prompt: str, conversation_history: list, user_message: str) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        recent = conversation_history[-(self.MAX_HISTORY_TURNS * 2):] if len(conversation_history) > self.MAX_HISTORY_TURNS * 2 else conversation_history
        for entry in recent:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content[:500]})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _validate_response(self, data: dict) -> bool:
        if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data.keys()):
            return False
        tool = data.get("tool")
        if not isinstance(tool, dict) or "name" not in tool or "args" not in tool:
            return False
        if not isinstance(data.get("missing_fields"), list):
            return False
        return True

    def _call_ollama(self, messages: list[dict]) -> dict | None:
        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"num_predict": 256, "temperature": 0.1},
        }
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Ollama timeout al clasificar intención")
            return None
        except (httpx.HTTPError, Exception) as e:
            logger.warning("Ollama no respondió: %s", e)
            return None
        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.warning("Respuesta de Ollama no es JSON válido")
            return None
        content = None
        if isinstance(data, dict):
            msg = data.get("message") or data.get("response")
            if isinstance(msg, dict):
                content = msg.get("content")
            elif isinstance(data.get("content"), str):
                content = data.get("content")
        if not content or not content.strip():
            logger.warning("Ollama devolvió contenido vacío")
            return None
        try:
            parsed = json.loads(content.strip())
        except json.JSONDecodeError:
            stripped = content.strip()
            if stripped.startswith("```"):
                for i, line in enumerate(stripped.split("\n")):
                    if "{" in line:
                        try:
                            parsed = json.loads("\n".join(stripped.split("\n")[i:]).replace("```", "").strip())
                            break
                        except json.JSONDecodeError:
                            pass
                else:
                    parsed = None
            else:
                parsed = None
            if parsed is None:
                logger.warning("No se pudo extraer JSON de la respuesta de Ollama")
                return None
        if not self._validate_response(parsed):
            logger.warning("Respuesta del LLM sin campos requeridos")
            return None
        return parsed

    def _extract_entities(self, user_message: str, intent: str, client_config: dict) -> tuple[dict, list[str]]:
        """Extrae entidades sin inventar. Retorna (tool_args, missing_fields)."""
        required = _get_required_fields(client_config, intent)
        lang = (client_config or {}).get("language", "es")
        is_en = isinstance(lang, str) and lang.strip().lower() == "en"

        args: dict = {}
        missing: list[str] = []

        if intent == "status":
            sid = _extract_shipment_id(user_message)
            if sid:
                args["shipment_id"] = str(sid)
            else:
                missing.append("shipment_id")

        elif intent == "reschedule":
            sid = _extract_shipment_id(user_message)
            if sid:
                args["shipment_id"] = str(sid)
            else:
                missing.append("shipment_id")
            date_val = _extract_new_date(user_message)
            if date_val:
                args["new_date"] = date_val
            else:
                missing.append("new_date")
            tw = _extract_new_time_window(user_message, lang)
            if tw:
                args["new_time_window"] = tw
            else:
                missing.append("new_time_window")

        elif intent == "ticket":
            sid = _extract_shipment_id(user_message)
            if sid:
                args["shipment_id"] = str(sid)
            else:
                missing.append("shipment_id")
            for f in ["issue_type", "description", "severity", "contact_name"]:
                if f in required and f not in args:
                    missing.append(f)

        return args, missing

    def classify(
        self,
        user_message: str,
        client_config: dict,
        conversation_history: list | None = None,
    ) -> dict:
        """
        Keyword-first: si pre-clasificador da un solo intent, usamos entidades y respuesta determinística.
        Si conflicto o sin match, llamamos LLM. Si LLM devuelve "other" y keywords sugieren intent → override.
        user_message siempre en config.language.
        """
        if conversation_history is None:
            conversation_history = []

        # 1) Saludo → other con greeting del config (orchestrator ya tiene fast path; por si se llama directo)
        if _is_greeting_only(user_message):
            return _build_deterministic_response("other", [], "none", {}, client_config)

        # 2) Pre-clasificador determinístico: un solo intent claro
        pre_intent = _preclassify_deterministic(user_message)
        if pre_intent and pre_intent != "other":
            required = _get_required_fields(client_config, pre_intent)
            args, missing = self._extract_entities(user_message, pre_intent, client_config)
            tool_name = _build_tool_name(pre_intent, args, required)
            if missing:
                tool_name = "none"
            return _build_deterministic_response(pre_intent, missing, tool_name, args, client_config)

        if pre_intent == "other":
            return _build_deterministic_response("other", [], "none", {}, client_config)

        # 3) Conflicto o sin match: usar LLM
        system_prompt = self._load_system_prompt(client_config)
        if not system_prompt:
            return get_fallback_response(client_config)
        messages = self._messages(system_prompt, conversation_history, user_message)
        parsed = self._call_ollama(messages)
        if parsed is None:
            # Fallback: si keywords sugieren algo, usar eso
            suggested = _keyword_suggested_intent(user_message)
            if suggested:
                required = _get_required_fields(client_config, suggested)
                args, missing = self._extract_entities(user_message, suggested, client_config)
                tool_name = "none" if missing else _build_tool_name(suggested, args, required)
                return _build_deterministic_response(suggested, missing, tool_name, args, client_config)
            return get_fallback_response(client_config)

        # Guardrail post-LLM: si el LLM respondió en idioma incorrecto, reescribir user_message
        if parsed is not None:
            llm_msg = parsed.get("user_message", "") or ""
            missing = parsed.get("missing_fields", []) or []
            args = (parsed.get("tool") or {}).get("args") or {}

            lang = (client_config or {}).get("language", "es")
            is_en = isinstance(lang, str) and lang.strip().lower() == "en"

            needs_rewrite = False
            # Heurística: si config es EN pero el mensaje tiene palabras clave ES
            if is_en and any(w in llm_msg.lower() for w in ["necesito", "envío", "envio", "indique", "puede", "formato"]):
                needs_rewrite = True
            # Si config es ES pero el mensaje huele a inglés
            if (not is_en) and any(w in llm_msg.lower() for w in ["provide", "please", "shipment", "could you"]):
                needs_rewrite = True

            if needs_rewrite:
                logger.info("Rewriting LLM user_message: wrong language detected")
                det = _build_deterministic_response(
                    parsed.get("intent", "other"),
                    missing,
                    (parsed.get("tool") or {}).get("name", "none"),
                    args,
                    client_config,
                )
                parsed["user_message"] = det["user_message"]

        intent = parsed.get("intent", "other")
        suggested = _keyword_suggested_intent(user_message)

        # 4) Override: LLM dijo "other" pero keywords sugieren reschedule/status/ticket
        if intent == "other" and suggested:
            logger.info("Override intent: other -> %s (keyword-first)", suggested)
            required = _get_required_fields(client_config, suggested)
            args, missing = self._extract_entities(user_message, suggested, client_config)
            tool_name = "none" if missing else _build_tool_name(suggested, args, required)
            return _build_deterministic_response(suggested, missing, tool_name, args, client_config)

        # 5) Validar/rellenar missing_fields desde required_fields si el LLM no los puso bien
        required = _get_required_fields(client_config, intent)
        tool = parsed.get("tool") or {}
        tool_name = tool.get("name", "none")
        args = dict(tool.get("args") or {})

        if intent == "reschedule" and not args.get("shipment_id"):
            args, missing = self._extract_entities(user_message, intent, client_config)
            if missing and not parsed.get("missing_fields"):
                parsed["missing_fields"] = missing
                parsed["tool"] = {"name": "none", "args": args}
                parsed["user_message"] = _build_deterministic_response(intent, missing, "none", args, client_config)["user_message"]
        elif intent in ("status", "reschedule", "ticket") and not args.get("shipment_id"):
            if "shipment_id" not in (parsed.get("missing_fields") or []):
                missing = list(parsed.get("missing_fields") or [])
                if "shipment_id" not in missing:
                    missing.insert(0, "shipment_id")
                parsed["missing_fields"] = missing
                parsed["tool"] = {"name": "none", "args": args}
                parsed["user_message"] = _build_deterministic_response(intent, missing, "none", args, client_config)["user_message"]

        logger.info("intent=%s tool.name=%s", parsed.get("intent"), parsed.get("tool", {}).get("name"))
        return parsed
