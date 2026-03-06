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

## Trade-offs del LLM (Ollama + qwen2.5:7b)

El uso de un modelo local de 7B parámetros tiene ventajas claras para este MVP, pero también implica limitaciones que condicionan el diseño del agente y la ingeniería de prompts.

### Ventajas del enfoque local

- **Adecuado para un MVP acotado:** con solo 3 intenciones (status, reschedule, ticket) y prompts bien diseñados, un modelo 7B es suficiente si se acota correctamente la tarea.

### Limitaciones observadas

- **Capacidad limitada de razonamiento profundo:** al ser un modelo de 7B, es más sensible a prompts largos o ambiguos y puede romper el formato JSON si se le pide “demasiado” en una sola instrucción.
- **Latencia perceptible en máquinas modestas:** especialmente cuando los prompts son extensos o se envía historial de conversación muy largo.
- **Sensibilidad al idioma y formato:** respetar siempre `config.language` (ES/EN) y el esquema de salida (`intent`, `missing_fields`, `tool`, etc.) requiere capas adicionales de validación en código.
- **Mayor probabilidad de “creatividad” indeseada:** sin guardrails, el modelo puede mezclar idiomas, inventar campos o alterar ligeramente el esquema JSON esperado.

### Mitigaciones de diseño aplicadas

- **Separación classifier / response builder:** dos prompts cortos y específicos en lugar de un único prompt monolítico:
  - El classifier se centra en intención, extracción de campos y elección de tool.
  - El response builder solo humaniza el resultado de la API, sin acceso directo a la lógica de negocio.
- **Pre-clasificador determinístico (keyword-first):**
  - Detecta de forma rápida `status`, `reschedule`, `ticket`, `other` usando palabras clave.
  - Reduce la dependencia del modelo para frases sencillas y frecuentes.
- **Control de generación en Ollama:**
  - `temperature=0.1` para priorizar salidas estables y predecibles frente a creatividad.
  - Historial truncado a unos pocos turnos recientes para limitar el tamaño del prompt y el ruido de contexto.
- **Guardrails en código:**
  - Heurísticas conservadoras para `shipment_id`, fechas y ventanas horarias; nunca se inventan valores.
  - Validación posterior a la llamada al LLM para corregir idioma (`user_message` en ES/EN según config) y rellenar `missing_fields` de forma determinista cuando sea necesario.
  - Fallbacks determinísticos cuando la respuesta del modelo no cumple el contrato (JSON inválido o incompleto).

### Posibles mejoras futuras

- **Modelo híbrido o de mayor capacidad:**
  - Evaluar modelos más grandes (locales o en la nube) para escenarios con más intenciones o diálogos complejos, manteniendo el mismo contrato JSON.

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
3. Documentación: README, SOW (este documento), RUNBOOK, PROMPT_NOTES, sample_conversations.
4. Evidencias: conversaciones de ejemplo (cuando existan en docs).