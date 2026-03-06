"""
Aplicación principal FastAPI: Logistics Agent Mock API.
"""

import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.middleware.logging_middleware import LoggingMiddleware
from api.middleware.metrics_middleware import MetricsMiddleware
from api.middleware.request_id_middleware import RequestIdMiddleware
from api.routes.shipments import get_shipment_service, router as shipments_router
from api.routes.tickets import get_ticket_service, router as tickets_router
from api.utils.exceptions import AppException
from api.utils.logger import get_logger, get_log_store, get_logs
from api.utils.metrics import get_metrics_collector

logger = get_logger(__name__)

# Health check: URL de Ollama (mismo que usa la UI por defecto)
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_HEALTH_TIMEOUT = 3.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Carga datos e inicializa servicios al arranque."""
    shipment_svc = get_shipment_service()
    ticket_svc = get_ticket_service()
    n = shipment_svc.count_shipments()
    logger.info("API started with %d shipments loaded", n)
    yield


app = FastAPI(
    title="Logistics Agent Mock API",
    version="1.0.0",
    description="""
## API de simulación para logística

- **Shipments**: consulta y reprogramación de envíos (datos desde `data/shipments.json`).
- **Tickets**: creación y listado de tickets de incidencias (en memoria).

Endpoints de utilidad: `GET /`, `GET /health`, `GET /metrics`, `GET /logs`.
    """.strip(),
    lifespan=lifespan,
)

@app.exception_handler(AppException)
def app_exception_handler(_request: Request, exc: AppException) -> JSONResponse:
    """Respuesta JSON consistente para todas las excepciones de aplicación."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


app.add_middleware(LoggingMiddleware)
app.add_middleware(MetricsMiddleware)  # actualiza requests_total, by_status, avg_response_time
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(shipments_router)
app.include_router(tickets_router)


@app.get(
    "/",
    summary="Root",
    description="Estado del servicio y versión.",
)
def root():
    """
    Devuelve el estado del servicio y la versión para comprobaciones rápidas.
    """
    return {
        "status": "ok",
        "service": "Logistics Mock API",
        "version": "1.0.0",
    }


def _check_ollama() -> dict:
    """GET a Ollama /api/tags con timeout 3s. Registra latencia en métricas."""
    metrics = get_metrics_collector()
    start = time.perf_counter()
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=OLLAMA_HEALTH_TIMEOUT)
        latency_ms = (time.perf_counter() - start) * 1000
        metrics.record_llm_call(latency_ms)
        return {
            "reachable": r.status_code == 200,
            "model": OLLAMA_MODEL,
            "latency_ms": round(latency_ms, 2),
        }
    except Exception:
        return {
            "reachable": False,
            "model": OLLAMA_MODEL,
            "latency_ms": None,
        }


@app.get(
    "/health",
    summary="Health check",
    description="Verifica JSON cargado, Ollama y tickets. Status healthy/degraded.",
)
def health():
    """
    Health check completo: JSON de shipments, Ollama (GET /api/tags), servicio de tickets.
    Overall "healthy" solo si todo está ok; "degraded" si alguna dependencia falla.
    """
    shipment_svc = get_shipment_service()
    ticket_svc = get_ticket_service()
    count_shipments = shipment_svc.count_shipments()
    count_tickets = ticket_svc.count_tickets()

    json_ok = count_shipments >= 0  # Cargado si el servicio respondió
    data_loaded = {"loaded": json_ok, "count": count_shipments}

    ollama_result = _check_ollama()
    ollama_ok = ollama_result.get("reachable", False)

    tickets_ok = True  # Servicio en memoria siempre "activo"
    tickets_data = {"active": tickets_ok, "count": count_tickets}

    all_ok = json_ok and ollama_ok and tickets_ok
    return {
        "status": "healthy" if all_ok else "degraded",
        "dependencies": {
            "data": data_loaded,
            "ollama": ollama_result,
            "tickets": tickets_data,
        },
    }


@app.get(
    "/metrics",
    summary="Métricas",
    description="Métricas básicas: requests_total, by_status, avg_response_time_ms, llm, tickets, uptime.",
)
def metrics():
    """
    Retorna métricas del MetricsCollector: contadores por endpoint/método y por status,
    latencia media por endpoint, llamadas LLM, tickets creados, uptime.
    """
    return get_metrics_collector().get_metrics()


@app.get(
    "/logs",
    summary="Últimos logs",
    description="Logs estructurados con filtros. Parámetros: limit, level (INFO/WARNING/ERROR), since (ISO).",
)
def logs(
    limit: int = 100,
    level: str | None = None,
    since: str | None = None,
):
    """
    Retorna logs del LogStore (máx. 500 en memoria) con formato JSON estructurado.
    Query params: limit (default 100), level (opcional), since (ISO timestamp).
    Incluye header X-Total-Count con el número de entradas que cumplen el filtro.
    """
    logs_list, total = get_logs(limit=limit, level_filter=level, since_timestamp=since)
    return JSONResponse(
        content=logs_list,
        headers={"X-Total-Count": str(total)},
    )
