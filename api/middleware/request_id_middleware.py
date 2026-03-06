"""
Middleware que asigna un request_id (UUID corto) por petición, lo propaga vía
contextvars para que todos los logs del request lo incluyan, y lo devuelve en
el header X-Request-ID.
"""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.utils.logger import clear_request_id, set_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Genera un request_id de 8 caracteres por request, lo almacena en contextvars
    para el logging estructurado y lo añade como X-Request-ID en la respuesta.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = uuid4().hex[:8]
        request.state.request_id = request_id
        set_request_id(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            clear_request_id()
