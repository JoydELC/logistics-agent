# Prompt Engineering Notes — Iteración, Pruebas y Refactor

---

## Versión Final del System Prompt (Resumen)

- **Dos llamadas al LLM:** (1) **Classifier** — identifica intención, extrae campos y decide tool/args o missing_fields; (2) **Response Builder** — humaniza la respuesta usando solo el resultado real de la API (TOOL_RESULT) y el tono/idioma del cliente.
- **Classifier:** devuelve **solo JSON** (sin markdown ni texto alrededor). Campos obligatorios: `intent`, `confidence`, `missing_fields`, `tool` (name + args), `user_message`. Se usa `format: "json"` en la llamada a Ollama cuando está disponible.
- **Response Builder:** humaniza **solo con datos reales** devueltos por la API; no inventa estados, ETA ni ubicaciones. Respeta `message_formats` y tono/idioma del config del cliente.
- **Guardrails:** no inventar shipment_id, fechas ni ventanas horarias; si falta algo, pedirlo con formato exacto (YYYY-MM-DD, mañana/tarde/noche o HH:MM-HH:MM). Saludos (hola, buenos días, hi) se manejan con `intent=other` y presentación breve usando `message_formats.greeting` si existe.

---

## Decisiones de Diseño

### 1) Dos prompts separados (Classifier + Response Builder)

- **Classifier** (`system_prompt_classifier.txt`): solo extrae intención, campos y herramienta; no genera texto libre de respuesta larga. Reduce alucinaciones en modelos 7B porque la tarea es acotada (clasificación + extracción).
- **Response Builder** (`system_prompt_response.txt`): recibe el TOOL_RESULT ya ejecutado y solo “frasea” en natural. La fuente de verdad es siempre la API, no el LLM.
- Ventaja: separación clara entre **qué hacer** (classifier) y **cómo decirlo** (response builder); el modelo no puede inventar datos en la fase de respuesta porque solo ve el JSON del backend.

### 2) Salida JSON obligatoria y parsing robusto

- En Ollama se usa `"format": "json"` en el body de `/api/chat` para indicar que la respuesta debe ser JSON.
- Regla en el prompt: *“Devuelve SIEMPRE un JSON válido. NO agregues texto fuera del JSON.”*
- En código: si la respuesta viene envuelta en markdown (backticks), el parser en `intent_classifier.py` intenta extraer el JSON (strip de ``` , búsqueda de la primera línea que empieza por `{`, `json.loads` sobre el bloque). Si falla o faltan claves requeridas, se devuelve un fallback seguro (intent=other, user_message genérico).

### 3) Guardrails anti-alucinación

- **Prohibido inventar:** status, ETA, ubicaciones, shipment_id, fechas. El prompt indica que “NO existe un status explícito en el JSON” y que “SOLO se puede usar lo que entregue la API”.
- **Si no hay shipment_id:** `tool.name = "none"`, `missing_fields` incluye `shipment_id`, y `user_message` pide solo el ID (sin sugerir uno).
- **Si el shipment no existe:** la API devuelve 404; el Response Builder recibe el error en TOOL_RESULT y debe responder con fallback honesto (no encontrado, verificar ID, ofrecer ticket o escalar). No inventar un estado ficticio.

### 4) Normalización de fechas y ventanas horarias

- **Ambigüedad “mañana”:** en español puede ser “morning” o “tomorrow”. En el prompt se fija: para **ventana horaria** se usan solo “mañana” (6–12h), “tarde” (12–18h), “noche” (18–24h) o “HH:MM-HH:MM”. Para **fecha**, no se convierte “mañana”/“el lunes” a fecha; se pide explícitamente “la fecha en formato YYYY-MM-DD”.
- Reglas documentadas en el classifier: si el usuario da solo una hora o algo vago, en `user_message` aclarar las opciones (mañana/tarde/noche o rango).

### 5) Límite de preguntas por turno

- En el prompt: *“Máximo 2 preguntas por turno (para no bombardear al usuario).”*
- En el orquestador: el historial de conversación se trunca a los últimos **MAX_HISTORY_MESSAGES** (10) para no enviar contextos excesivamente largos al classifier y mantener respuestas coherentes.

### 6) Clasificador keyword-first determinístico

- Además del prompt del classifier, se añadió una capa **keyword-first determinística** en `agent/intent_classifier.py`:
  - Usa listas de palabras clave para detectar de forma rápida si el mensaje apunta claramente a `status`, `reschedule`, `ticket` u `other` sin necesidad de llamar al LLM.
  - Para estas intenciones, el classifier intenta extraer de forma conservadora solo los campos que estén inequívocamente presentes en el texto (`shipment_id`, `new_date`, `new_time_window`), y delega al LLM solo cuando hay conflicto o ambigüedad.
- Esta capa reduce la carga sobre el modelo `qwen2.5:7b`, mejora latencia y hace el comportamiento más estable en frases cortas y muy frecuentes.

### 7) Heurísticas conservadoras para `shipment_id`

- `_extract_shipment_id` se rediseñó para ser **conservador por defecto**:
  - Solo acepta tokens que contienen dígitos (ej. `14309635`, `ABC123`, `A-1234`) o números puros con longitud mínima.
  - Nunca trata palabras comunes en inglés/español (`delivery`, `order`, `shipment`, `package`, `paquete`, `envío`, etc.) como IDs, aunque encajen sintácticamente.
- Lección de pruebas:
  - Caso problemático: `"I need to reschedule my delivery"` con el cliente EN.
  - Antes del cambio, la heurística podía interpretar `delivery` como `shipment_id` y el mensaje posterior solo pedía fecha/ventana.
  - Con el enfoque conservador, el clasificador marca `shipment_id` como faltante y el `user_message` pide explícitamente el ID del envío; la fecha y la ventana se piden después o en el mismo turno, respetando la regla de máximo dos preguntas.

### 8) Guardrails de idioma y `temperature=0.1` en Ollama

- En iteraciones recientes se observó que el modelo local 7B puede:
  - Mezclar idiomas (responder en ES cuando el cliente está configurado en EN y viceversa).
  - Romper el formato JSON cuando el prompt es largo o la temperatura es alta.
- Mitigaciones implementadas:
  - **Idioma:**
    - El classifier valida que `user_message` esté SIEMPRE en `config.language` (ES/EN).
    - Si el LLM responde en el idioma incorrecto, el classifier reescribe el `user_message` con una respuesta determinística basada en `missing_fields` y la configuración YAML del cliente.
  - **Estabilidad de formato:**
    - Se fijó `temperature=0.1` en las llamadas a Ollama tanto para el classifier como para el response builder.
    - Se limitó el historial enviado al modelo a unos pocos turnos recientes (truncando y recortando contenido) para reducir ruido y probabilidad de salirse del esquema JSON.
- Resultado: menos alucinaciones, respuestas más consistentes con el idioma del cliente y un JSON de salida más estable para el parser.

### 9) Manejo de contexto multi-turn en el orquestador

- Para soportar flujos donde el usuario aporta los datos en varios turnos, el `AgentOrchestrator` gestiona un contexto pendiente:
  - Se guardan `_pending_intent` y `_pending_args` cuando el classifier devuelve `missing_fields` (por ejemplo, falta `shipment_id` o `new_date`).
  - Turno 1: `"I need to reschedule"` → `intent=reschedule`, se identifican los campos requeridos y el mensaje pide shipment_id/fecha/ventana en el idioma configurado.
  - Turno 2: `"shipment 1395083, 2026-03-10, afternoon"` → el orquestador fusiona estos nuevos datos con los pendientes, reevalúa `missing_fields` y, si ya están completos (`shipment_id`, `new_date`, `new_time_window`), dispara la herramienta `POST /shipments/{id}/reschedule`.
- Este diseño mantiene la lógica del prompt (máximo dos preguntas, no inventar datos) pero mejora la experiencia multi-turn sin sobrecargar al LLM con más instrucciones.