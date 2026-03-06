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
        logger.info("Orchestrator initialized for client: %s", self.client_name)

    def _trim_history(self) -> None:
        """Mantiene solo los últimos MAX_HISTORY_MESSAGES mensajes."""
        if len(self.conversation_history) > MAX_HISTORY_MESSAGES:
            self.conversation_history = self.conversation_history[-MAX_HISTORY_MESSAGES:]

    async def process_message(self, user_message: str) -> dict:
        """
        Flujo principal: clasificar → si hay herramienta y no faltan campos, ejecutar
        y construir respuesta con ResponseBuilder; si no, devolver la respuesta del classifier.
        Actualiza el historial y lo limita a los últimos 10 mensajes.
        """
        if not (user_message and user_message.strip()):
            return {
                "intent": "other",
                "confidence": 0.0,
                "missing_fields": [],
                "tool": {"name": "none", "args": {}},
                "user_message": "No recibí ningún mensaje. ¿En qué puedo ayudarle?",
            }

        try:
            result = self.classifier.classify(
                user_message,
                self.client_config,
                self.conversation_history,
            )
        except Exception as e:
            logger.exception("Error al clasificar: %s", e)
            return {
                "intent": "other",
                "confidence": 0.0,
                "missing_fields": [],
                "tool": {"name": "none", "args": {}},
                "user_message": "Lo siento, hubo un error al procesar su mensaje. ¿Puede reformularlo?",
            }

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
                )

            final_response["meta"] = {"tool_result": tool_result, "duration_ms": round(duration_ms, 2)}
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": final_response.get("user_message", "")})
            self._trim_history()
            return final_response
        else:
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": result.get("user_message", "")})
            self._trim_history()
            return result

    def reset_conversation(self) -> None:
        """Limpia el historial de conversación."""
        self.conversation_history = []
        logger.info("Conversation reset for client: %s", self.client_name)

    def get_conversation_history(self) -> list:
        """Retorna el historial actual (lista de {role, content})."""
        return list(self.conversation_history)
