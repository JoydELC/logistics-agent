# Prompt Engineering Notes — Iteración, Pruebas y Refactor

Documento de decisiones de diseño, pruebas realizadas y problemas resueltos durante el desarrollo del agente conversacional de logística, incluyendo el refactor de validación, excepciones, logging estructurado, request_id, métricas y UI de debugging.

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
- En código: si la respuesta viene envuelta en markdown (backticks), el parser en `intent_classifier.py` intenta extraer el JSON (strip de ` ``` `, búsqueda de la primera línea que empieza por `{`, `json.loads` sobre el bloque). Si falla o faltan claves requeridas, se devuelve un fallback seguro (intent=other, user_message genérico).

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