"""
Logging con formato JSON estructurado, request_id vía contextvars y LogStore en memoria.
"""

import json
import logging
import os
import contextvars
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

# Contextvar para que todos los logs del request incluyan el mismo request_id
_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def set_request_id(request_id: str) -> None:
    """Establece el request_id del request actual (llamado por el middleware)."""
    _request_id_ctx.set(request_id)


def clear_request_id() -> None:
    """Limpia el request_id al finalizar el request."""
    try:
        _request_id_ctx.set(None)
    except LookupError:
        pass


def get_request_id() -> str | None:
    """Obtiene el request_id del contexto actual para incluirlo en los logs."""
    return _request_id_ctx.get(None)


# LogStore: últimos 500 logs como listas de dicts (buffer circular)
LOG_STORE_MAX = 500
_log_store: deque[dict[str, Any]] = deque(maxlen=LOG_STORE_MAX)


def get_log_store() -> deque[dict[str, Any]]:
    """Retorna el deque del LogStore (últimos 500 logs como dicts)."""
    return _log_store


def get_logs(
    limit: int = 100,
    level_filter: str | None = None,
    since_timestamp: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Devuelve logs filtrados del LogStore.

    Args:
        limit: Máximo de entradas a devolver (más recientes primero).
        level_filter: Filtrar por nivel (INFO, WARNING, ERROR). None = todos.
        since_timestamp: Filtrar entradas con timestamp >= este valor (ISO).

    Returns:
        (lista de dicts de log, total_count que cumplen el filtro sin limit).
    """
    store = list(_log_store)
    if level_filter:
        level_upper = level_filter.upper()
        store = [e for e in store if e.get("level") == level_upper]
    if since_timestamp:
        try:
            since_dt = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
            store = [e for e in store if e.get("timestamp") and datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) >= since_dt]
        except (ValueError, TypeError):
            pass
    total = len(store)
    # Más recientes primero: tomar los últimos `limit`
    selected = store[-limit:][::-1]
    return selected, total


# Claves estándar de LogRecord que no van a "extra"
_STANDARD_RECORD_KEYS = frozenset({
    "name", "msg", "args", "created", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs",
    "pathname", "process", "processName", "relativeCreated",
    "stack_info", "exc_info", "exc_text", "thread", "threadName",
    "message", "taskName",
})


class JsonFormatter(logging.Formatter):
    """
    Formatea cada log como JSON con:
    timestamp (ISO), level, logger, request_id, message, extra.
    """

    def format(self, record: logging.LogRecord) -> str:
        extra: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and value is not None:
                try:
                    if isinstance(value, (str, int, float, bool, type(None))):
                        extra[key] = value
                    else:
                        extra[key] = str(value)
                except Exception:
                    extra[key] = "<unserializable>"
        if record.exc_info:
            extra["exception"] = self.formatException(record.exc_info)

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": get_request_id(),
            "message": record.getMessage(),
            "extra": extra,
        }
        return json.dumps(payload, ensure_ascii=False)


class LogStoreHandler(logging.Handler):
    """Handler que añade cada log como dict al LogStore y delega en el target."""

    def __init__(self, target_handler: logging.Handler, formatter: logging.Formatter) -> None:
        super().__init__()
        self._target = target_handler
        self._formatter = formatter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self._formatter.format(record)
            entry = json.loads(msg)
            _log_store.append(entry)
        except Exception:
            pass
        self._target.emit(record)


def get_logger(name: str) -> logging.Logger:
    """
    Retorna un logger configurado con formato JSON (timestamp, level, logger,
    request_id, message, extra), consola, archivo rotativo y LogStore (500 entradas).
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    formatter = JsonFormatter()

    # Consola
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    # Archivo rotativo
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    log_dir = os.path.join(root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "api.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # LogStore + consola
    store_handler = LogStoreHandler(console, formatter)
    store_handler.setLevel(logging.INFO)
    logger.addHandler(store_handler)
    logger.addHandler(file_handler)

    return logger
