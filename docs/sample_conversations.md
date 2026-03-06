# Sample Conversations — Guía de validación

Documento para validar el agente de forma sencilla: idioma según cliente, errores consistentes (AppException), y que no invente ni asuma datos. Incluye request_id y debug info en UI.

---

## Cómo validar

1. **Cliente y idioma:** En la UI, elegir **QuickShip** para inglés y **TransLogistics Corp** para español. Todas las respuestas del agente deben estar en ese idioma.
2. **Debug:** En cada respuesta del asistente, abrir el expander **"Detalles técnicos"** para ver intent, tool, tool_result y latencia.
3. **API:** Las respuestas HTTP incluyen el header **X-Request-ID**; en **GET /logs** se puede filtrar por ese ID para seguir la traza.

---

## Escenario 1: Consulta de estado (ES, formal)

**Cliente:** TransLogistics Corp (español, formal)

| Paso | Acción | 
|------|--------|
| 1 | Usuario: *¿Cuál es el estado del envío 14309635?* | 
| 2 | Respuesta | *Estimado usuario, le informo sobre el envío 14309635: tipo DE, estado [derivado], origen/destino según API. [ETA si la API la incluye].* |

---

## Escenario 2: Reprogramación en inglés (EN, casual)

**Cliente:** QuickShip (inglés, casual)

| Paso | Acción | 
|------|--------|
| 1 | Usuario: *I need to reschedule my delivery* |
| 2 | Respuesta: *Sure, I can help with that. Could you please provide the new date in YYYY-MM-DD format, e.g. 2025-03-15, and the new time window? You can choose: morning (6-12), afternoon (12-18), evening (18-24), or a range like 09:00-14:00.* | 
| 3 | Usuario: *14309635, 2025-02-20, afternoon* | 
| 4 | Respuesta: *All set! Shipment 14309635 has been rescheduled to 2025-02-20 (afternoon).* | 


---
## Escenario 3: Envío no encontrado (404)

**Cliente:** Cualquiera

| Paso | Acción | Qué validar |
|------|--------|-------------|
| 1 | Usuario: *Estado del envío 99999* |
| 2 | Respuesta: *No se encontró información para el envío con ID 99999. Verifique el número e intente nuevamente.* | 
---

