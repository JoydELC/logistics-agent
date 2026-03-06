"""
Middleware de logging: intercepta cada request/response y loguea con request_id.
El request_id lo establece RequestIdMiddleware (contextvars + X-Request-ID).
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.utils.logger import get_logger

logger = get_logger(__name__)
RESPONSE_PREVIEW_MAX = 200


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Intercepta cada request/response; loguea method, path, status_code, duration_ms.
    request_id viene de RequestIdMiddleware (ya en contextvars). INFO 2xx, WARNING 4xx, ERROR 5xx.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = getattr(request.state, "request_id", None)
        start = time.perf_counter()

        request_body_preview: str | None = None
        if request.method in ("POST", "PUT", "PATCH"):
            request_body_preview = "(body not logged to avoid consuming stream)"

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response_preview = f"status={response.status_code}"[:RESPONSE_PREVIEW_MAX]

        extra = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "response_preview": response_preview,
        }
        if request_id is not None:
            extra["request_id"] = request_id
        if request_body_preview is not None:
            extra["request_body"] = request_body_preview

        if 200 <= response.status_code < 300:
            logger.info(
                "%s %s %s %.2fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra=extra,
            )
        elif 400 <= response.status_code < 500:
            logger.warning(
                "%s %s %s %.2fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra=extra,
            )
        else:
            logger.error(
                "%s %s %s %.2fms",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                extra=extra,
            )
        return response
