"""
Middleware que actualiza las métricas por cada request: contadores y latencia.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.utils.metrics import get_metrics_collector


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Tras cada request incrementa requests_total (por método y path),
    requests_by_status (por código) y registra la latencia para avg_response_time_ms.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        collector = get_metrics_collector()
        collector.record_request(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
