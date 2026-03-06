# Runbook — Logistics Agent

Guía operativa para poner en marcha y operar el agente conversacional, la Mock API y la UI, con referencia a observabilidad (request-id, logs estructurados, /health, /metrics, /logs).

---

## Servicios y Puertos

| Servicio           | Comando                                              | Puerto | Verificación                                      |
|--------------------|------------------------------------------------------|--------|---------------------------------------------------|
| Ollama             | `ollama serve`                                       | 11434  | `curl http://localhost:11434/api/tags`             |
| Mock API (FastAPI) | `uvicorn api.main:app --reload --port 8000`          | 8000   | `curl http://localhost:8000/health`               |
| Streamlit UI       | `streamlit run ui/app.py`                            | 8501   | Abrir `http://localhost:8501`                     |

---

## Inicio Completo

```bash
# Terminal 1 — LLM
ollama serve

# Terminal 2 — API
cd logistics-agent && source venv/bin/activate
uvicorn api.main:app --reload --port 8000

# Terminal 3 — UI
cd logistics-agent && source venv/bin/activate
streamlit run ui/app.py
```
- **UI:** http://localhost:8501  


