"""
Singleton MetricsCollector para observabilidad: contadores y latencias.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Any

# Límite de muestras por endpoint para avg (evitar crecimiento infinito)
MAX_SAMPLES_PER_ENDPOINT = 10_000
MAX_LLM_LATENCIES = 1_000


class MetricsCollector:
    """
    Recopila métricas de la API: requests por endpoint/método, por status,
    tiempos de respuesta, llamadas LLM, tickets creados, uptime.
    Thread-safe.
    """

    _instance: "MetricsCollector | None" = None
    _lock = Lock()

    def __new__(cls) -> "MetricsCollector":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._lock = Lock()
        self._start_time = time.monotonic()
        # requests_total: clave "METHOD /path" -> count
        self._requests_total: dict[str, int] = defaultdict(int)
        # requests_by_status: status_code -> count
        self._requests_by_status: dict[int, int] = defaultdict(int)
        # response_times: "METHOD /path" -> list of ms (últimas N para avg)
        self._response_times: dict[str, list[float]] = defaultdict(list)
        self._llm_calls_total = 0
        self._llm_latencies: list[float] = []
        self._tickets_created = 0
        self._initialized = True

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        """Registra una petición HTTP (llamado por el middleware)."""
        key = f"{method} {path}"
        with self._lock:
            self._requests_total[key] += 1
            self._requests_by_status[status_code] += 1
            times = self._response_times[key]
            times.append(duration_ms)
            if len(times) > MAX_SAMPLES_PER_ENDPOINT:
                times.pop(0)

    def record_llm_call(self, latency_ms: float) -> None:
        """Registra una llamada a Ollama/LLM (p. ej. desde health check)."""
        with self._lock:
            self._llm_calls_total += 1
            self._llm_latencies.append(latency_ms)
            if len(self._llm_latencies) > MAX_LLM_LATENCIES:
                self._llm_latencies.pop(0)

    def record_ticket_created(self) -> None:
        """Registra la creación de un ticket."""
        with self._lock:
            self._tickets_created += 1

    def uptime_seconds(self) -> float:
        """Segundos desde el arranque."""
        return time.monotonic() - self._start_time

    def get_metrics(self) -> dict[str, Any]:
        """
        Devuelve el dict para GET /metrics.
        Incluye requests_total, requests_by_status, avg_response_time_ms por endpoint,
        llm_calls_total, llm_avg_latency_ms, tickets_created, uptime_seconds.
        """
        with self._lock:
            requests_total = dict(self._requests_total)
            requests_by_status = {str(k): v for k, v in self._requests_by_status.items()}
            avg_response_time_ms: dict[str, float] = {}
            for key, times in self._response_times.items():
                if times:
                    avg_response_time_ms[key] = round(sum(times) / len(times), 2)
            llm_avg = (
                round(sum(self._llm_latencies) / len(self._llm_latencies), 2)
                if self._llm_latencies
                else 0.0
            )
        return {
            "requests_total": requests_total,
            "requests_by_status": requests_by_status,
            "avg_response_time_ms": avg_response_time_ms,
            "llm_calls_total": self._llm_calls_total,
            "llm_avg_latency_ms": llm_avg,
            "tickets_created": self._tickets_created,
            "uptime_seconds": round(self.uptime_seconds(), 2),
        }


def get_metrics_collector() -> MetricsCollector:
    """Devuelve la instancia singleton del MetricsCollector."""
    return MetricsCollector()
