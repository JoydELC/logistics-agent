# 🚚 Logistics Agent — AI-Powered Shipment Management

## Overview

Agente conversacional que gestiona envíos usando **LLM local (Ollama)** + **Mock API (FastAPI)** + **UI (Streamlit)**.

- **3 intenciones:** consulta de estado, reprogramación, tickets de incidencia.
- **Configurable por cliente:** tono, idioma, políticas (YAML en `configs/`).
- **Observabilidad:** logs estructurados JSON con Request-ID, health checks completos, métricas y UI con panel de actividad (filtros por nivel, endpoint, últimos N minutos).

## Architecture

```
[User] → [Streamlit UI] → [Agent Orchestrator]
                                    ↓
                          [Intent Classifier (LLM)]
                                    ↓
                [Tool Executor → FastAPI Mock API (+ Middleware)]
                                    ↓
                  [Shipments/Tickets Services + Validation + Exceptions]
                                    ↓
              [Structured Logging + MetricsCollector + /health + /metrics]
                                    ↓
                          [Response Builder (LLM)]
                                    ↓
                          [Formatted Response → UI]
```

## Requirements

- **Python 3.10+**
- **Ollama** con modelo `qwen2.5:7b`
- ~4 GB RAM libres para el LLM

## Quick Start (< 10 minutes)

### 1. Clone & Setup

```bash
git clone <repo>
cd logistics-agent
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start Ollama

```bash
ollama pull qwen2.5:7b
ollama serve   # Dejar corriendo en Terminal 1
```

### 3. Start Mock API

```bash
uvicorn api.main:app --reload --port 8000   # Terminal 2
```

### 4. Start UI

```bash
streamlit run ui/app.py   # Terminal 3
```

- **UI:** http://localhost:8501

---

## Key Endpoints (API)

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Estado y versión del servicio |
| GET | `/health` | Health check completo: JSON cargado, Ollama reachable, tickets active. Status `healthy` o `degraded` |
| GET | `/metrics` | Métricas: `requests_total`, `requests_by_status`, `avg_response_time_ms`, `llm_calls_total`, `llm_avg_latency_ms`, `tickets_created`, `uptime_seconds` |
| GET | `/logs` | Logs estructurados JSON. Params: `limit`, `level` (INFO/WARNING/ERROR), `since` (ISO). Header `X-Total-Count` |
| GET | `/shipments` | Listado paginado (`limit`, `offset`, `order_type`) |
| GET | `/shipments/{shipment_id}` | Detalle de envío (incl. `derived_status`, `eta_info`) |
| POST | `/shipments/{shipment_id}/reschedule` | Reprogramar (body: `new_date`, `new_time_window`, `note`) |
| GET | `/tickets` | Lista de tickets (opcional `?shipment_id=`) |
| POST | `/tickets` | Crear ticket (body: `shipment_id`, `issue_type`, `description`, `severity`, `contact`) |

Validación: `shipment_id` solo permite `^[a-zA-Z0-9\-\s]+$`. Si no cumple → 400. Envío no encontrado → 404 (excepciones propias en JSON).

## Project Structure

```
logistics-agent/
├── api/
│   ├── main.py              # FastAPI app, /health, /metrics, /logs, exception handler
│   ├── middleware/
│   │   ├── logging_middleware.py
│   │   ├── metrics_middleware.py
│   │   └── request_id_middleware.py
│   ├── models/              # Pydantic (shipment, ticket)
│   ├── routes/
│   │   ├── shipments.py
│   │   └── tickets.py
│   ├── services/
│   │   ├── shipment_service.py
│   │   └── ticket_service.py
│   └── utils/
│       ├── exceptions.py    # AppException, ShipmentNotFoundError, InvalidShipmentIdError, etc.
│       ├── logger.py        # LogStore (dict-based), JSON structured logs, request_id (contextvars)
│       └── metrics.py       # MetricsCollector singleton
├── agent/
│   ├── intent_classifier.py
│   ├── response_builder.py
│   ├── tool_executor.py
│   ├── orchestrator.py
│   └── prompts/
│       ├── system_prompt_classifier.txt
│       └── system_prompt_response.txt
├── configs/
│   ├── client_a_formal.yaml
│   └── client_b_casual.yaml
├── data/
│   └── shipments.json
├── ui/
│   └── app.py               # Streamlit: chat, panel de logs (filtros, cards), sidebar (API/LLM status)
├── requirements.txt
└── README.md
```

- **api:** Mock API con validación, excepciones propias, middleware de request_id, métricas y logs JSON.
- **agent:** Clasificador de intenciones (Ollama), ejecutor de herramientas, constructor de respuestas.
- **configs:** YAML por cliente (idioma, tono, políticas, message_formats).
- **ui:** Streamlit con selector de cliente, chat y panel de actividad (logs con filtros y cards).
- **tests:** pytest para API (TestClient) y agente (Ollama mockeado).

---

## Configuration

Dos plantillas de cliente en `/configs`:

- **client_a_formal.yaml:** español, tono formal (TransLogistics Corp).
- **client_b_casual.yaml:** inglés, tono casual (QuickShip).

El config se elige en la **UI (Streamlit)** mediante el selector "Cliente" en el sidebar. No hay variable de entorno ni argumento de línea de comandos: la UI usa el cliente seleccionado para instanciar el `AgentOrchestrator` con la ruta del YAML correspondiente.

---

## Troubleshooting

| Issue | Causa / Fix |
|-------|-------------|
| **400 Invalid shipment_id** | Solo se permiten letras, números, guiones y espacios (`^[a-zA-Z0-9\-\s]+$`). Quitar caracteres especiales. |
| **/health "degraded"** | Ollama no está reachable. Comprobar `ollama serve` y que `http://localhost:11434/api/tags` responda. |
| **JSON parse error del LLM** | El modelo devolvió texto no JSON o sin los campos requeridos. Reintentar o revisar prompts. |
| **Logs vacíos o /logs no responde** | El LogStore guarda los últimos 500 logs en memoria. Comprobar que la API esté recibiendo requests (p. ej. abrir la UI o llamar a /health). |
| **UI no actualiza / auto-refresh** | Streamlit recarga al interactuar. El panel de logs se actualiza en cada interacción con la página; no hay polling automático. |

---

## Docs

Documentación adicional que el proyecto puede incluir (según implementación actual):

- **docs/SOW.md** — Scope y supuestos del proyecto.
- **docs/RUNBOOK.md** — Guía de operaciones.
- **docs/PROMPT_NOTES.md** — Iteraciones de prompts y notas del refactor.
- **docs/sample_conversations.md** — Conversaciones de prueba.
