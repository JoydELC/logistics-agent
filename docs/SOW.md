# Statement of Work — Logistics Conversational Agent (MVP)

## Objetivo

Construir un agente conversacional para gestión de envíos (mock) con operación local en **menos de 10 minutos**, enfocado en confiabilidad y observabilidad.

## Alcance (Incluye)

- **Agente conversacional** para gestión de envíos.
- **3 intenciones:**
  1. Consulta de estado (por `shipment_id`).
  2. Reprogramación (fecha y ventana horaria).
  3. Creación de tickets de incidencia (daño, retraso, pérdida, etc.).
- **Mock API** con endpoints de shipments y tickets.
- **Configuración por cliente** (tono, idioma, políticas) vía YAML en `configs/`.
- **UI de chat** (Streamlit) con panel de actividad y debugging (logs con filtros, cards por nivel).
- **Validación robusta de inputs:**
  - `shipment_id`: regex `^[a-zA-Z0-9\-\s]+$`; respuestas 400 con mensaje claro si no cumple.
  - Tickets: `description` min 5 / max 500 caracteres; validación básica de email y phone cuando se proporcionan.
- **Manejo de errores consistente** vía `AppException` y handlers globales (JSON: `error`, `detail`, `status_code`, `timestamp`).

## Stack Tecnológico

- **LLM:** Ollama + qwen2.5:7b (local).
- **Backend:** FastAPI (Python 3.10+).
- **UI:** Streamlit.
- **Data:** JSON en memoria (`data/shipments.json`); tickets en memoria (sin persistencia).
- **Testing:** pytest, httpx (TestClient), unittest.mock.

## Supuestos

- `data/shipments.json` es la fuente de verdad de shipments; la API carga el archivo al arranque (lifespan).
- No hay autenticación.
- Los tickets se almacenan en memoria y se pierden al reiniciar la API.
- El estado del envío se deriva de fechas (no existe campo explícito en el JSON original); la API expone `derived_status` y `eta_info`.
- Soporte de máximo 2 idiomas (ES/EN) según config del cliente.
- Ollama puede estar caído: **/health** reporta `degraded` y la UI muestra el estado (sidebar API/LLM).

## Entregables

1. Código fuente del agente + API + UI.
2. Configuración por cliente (2 templates: `client_a_formal.yaml`, `client_b_casual.yaml`).
3. Documentación: README, SOW (este documento), RUNBOOK, PROMPT_NOTES, sample_conversations 
4. Evidencias: conversaciones de ejemplo (cuando existan en docs).

