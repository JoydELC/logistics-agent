"""
Clasificador de intenciones usando Ollama (qwen2.5).
"""

import json
import logging
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

FALLBACK_RESPONSE = {
    "intent": "other",
    "confidence": 0.0,
    "missing_fields": [],
    "tool": {"name": "none", "args": {}},
    "user_message": "Lo siento, no pude procesar tu solicitud. ¿Puedes reformularla?",
}

REQUIRED_KEYS = {"intent", "confidence", "missing_fields", "tool", "user_message"}


class IntentClassifier:
    """
    Clasifica la intención del usuario y prepara la herramienta a ejecutar
    usando el LLM vía API de Ollama.
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
        """Carga el prompt del archivo y reemplaza {{CLIENT_CONFIG_JSON}}."""
        try:
            text = self._prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("No se pudo cargar system_prompt_classifier.txt: %s", e)
            return ""
        config_json = json.dumps(client_config, ensure_ascii=False, indent=2)
        return text.replace("{{CLIENT_CONFIG_JSON}}", config_json)

    def _messages(self, system_prompt: str, conversation_history: list, user_message: str) -> list[dict]:
        """Construye la lista de mensajes para la API de Ollama."""
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for entry in conversation_history:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _validate_response(self, data: dict) -> bool:
        """Comprueba que la respuesta tenga los campos requeridos."""
        if not isinstance(data, dict):
            return False
        if not REQUIRED_KEYS.issubset(data.keys()):
            return False
        tool = data.get("tool")
        if not isinstance(tool, dict) or "name" not in tool or "args" not in tool:
            return False
        if not isinstance(data.get("missing_fields"), list):
            return False
        return True

    def classify(
        self,
        user_message: str,
        client_config: dict,
        conversation_history: list | None = None,
    ) -> dict:
        """
        Clasifica el mensaje del usuario, reemplaza el placeholder de config,
        llama a Ollama y devuelve el JSON parseado o un fallback seguro.
        """
        if conversation_history is None:
            conversation_history = []

        system_prompt = self._load_system_prompt(client_config)
        messages = self._messages(system_prompt, conversation_history, user_message)

        url = f"{self.ollama_base_url}/api/chat"
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=body)
                response.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Ollama timeout al clasificar intención")
            return FALLBACK_RESPONSE
        except (httpx.HTTPError, Exception) as e:
            logger.warning("Ollama no respondió: %s", e)
            return FALLBACK_RESPONSE

        try:
            data = response.json()
        except json.JSONDecodeError:
            logger.warning("Respuesta de Ollama no es JSON válido")
            return FALLBACK_RESPONSE

        # Ollama devuelve {"message": {"content": "..."}} en /api/chat
        content = None
        if isinstance(data, dict):
            msg = data.get("message") or data.get("response")
            if isinstance(msg, dict):
                content = msg.get("content")
            elif isinstance(data.get("content"), str):
                content = data.get("content")

        if not content or not content.strip():
            logger.warning("Ollama devolvió contenido vacío")
            return FALLBACK_RESPONSE

        try:
            parsed = json.loads(content.strip())
        except json.JSONDecodeError:
            # Intentar extraer JSON de un bloque de texto
            stripped = content.strip()
            if stripped.startswith("```"):
                lines = stripped.split("\n")
                for i, line in enumerate(lines):
                    if line.strip().startswith("{"):
                        try:
                            parsed = json.loads("\n".join(lines[i:]).replace("```", "").strip())
                            break
                        except json.JSONDecodeError:
                            pass
                else:
                    parsed = None
            else:
                parsed = None
            if parsed is None:
                logger.warning("No se pudo extraer JSON de la respuesta de Ollama")
                return FALLBACK_RESPONSE

        if not self._validate_response(parsed):
            logger.warning("Respuesta del LLM sin campos requeridos: %s", list(parsed.keys()) if isinstance(parsed, dict) else type(parsed))
            return FALLBACK_RESPONSE

        intent = parsed.get("intent", "other")
        confidence = float(parsed.get("confidence", 0))
        tool_name = (parsed.get("tool") or {}).get("name", "none")
        logger.info("intent=%s confidence=%s tool.name=%s", intent, confidence, tool_name)
        return parsed
