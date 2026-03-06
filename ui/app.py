"""
Interfaz Streamlit: chat con el agente de logística y panel de logs.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import html

import httpx
import streamlit as st

# Rutas de config para los dos clientes (desde raíz del proyecto)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = {
    "TransLogistics Corp (ES, Formal)": PROJECT_ROOT / "configs" / "client_a_formal.yaml",
    "QuickShip (EN, Casual)": PROJECT_ROOT / "configs" / "client_b_casual.yaml",
}
API_BASE = "http://localhost:8000"
OLLAMA_BASE = "http://localhost:11434"


def get_orchestrator(client_key: str):
    """Crea o devuelve el orchestrator para el cliente seleccionado."""
    from agent.orchestrator import AgentOrchestrator

    path = CONFIGS.get(client_key)
    if not path or not path.is_file():
        raise FileNotFoundError(f"Config no encontrado: {client_key}")
    return AgentOrchestrator(
        client_config_path=str(path),
        ollama_url=OLLAMA_BASE,
        api_url=API_BASE,
        model="qwen2.5:7b",
    )


def check_api_health() -> bool:
    try:
        r = httpx.get(f"{API_BASE}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def check_ollama_health() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def fetch_logs(limit: int = 100, level: str | None = None, since: str | None = None) -> list:
    """Obtiene logs de la API (array JSON; opcional limit, level, since)."""
    try:
        params = {"limit": limit}
        if level:
            params["level"] = level
        if since:
            params["since"] = since
        r = httpx.get(f"{API_BASE}/logs", params=params, timeout=5.0)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


# --- Session state ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "client_key" not in st.session_state:
    st.session_state.client_key = "TransLogistics Corp (ES, Formal)"
if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = None
if "logs" not in st.session_state:
    st.session_state.logs = []
if "show_info" not in st.session_state:
    st.session_state.show_info = True
if "show_warning" not in st.session_state:
    st.session_state.show_warning = True
if "show_error" not in st.session_state:
    st.session_state.show_error = True
if "logs_cleared" not in st.session_state:
    st.session_state.logs_cleared = False
if "logs_cleared_at" not in st.session_state:
    st.session_state.logs_cleared_at = None
if "logs_raw" not in st.session_state:
    st.session_state.logs_raw = []


# --- Page config y CSS ---
st.set_page_config(
    page_title="Logistics Agent",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Session state para filtros del panel de logs
if "filter_endpoint" not in st.session_state:
    st.session_state.filter_endpoint = "All"
if "filter_minutes" not in st.session_state:
    st.session_state.filter_minutes = 15
if "last_logs_refresh" not in st.session_state:
    st.session_state.last_logs_refresh = None

st.markdown(
    """
<style>
    /* Tema oscuro base */
    .stApp { background-color: #0e1117; }
    [data-testid="stHeader"] { background: #1a1d24; }
    
    /* Header del panel de logs */
    .log-panel-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem; }
    .log-panel-title { font-size: 1.1rem; font-weight: 600; color: #f0f2f6; }
    .log-badge { display: inline-block; padding: 0.2rem 0.5rem; border-radius: 12px; font-size: 0.75rem; font-weight: 600; background: #31333b; color: #b0b4bc; }
    .log-refresh-ts { font-size: 0.7rem; color: #6c757d; font-family: monospace; }
    
    /* Cards de log */
    .log-card { 
        padding: 0.6rem 0.85rem; margin: 0.35rem 0; border-radius: 8px; 
        font-size: 0.82rem; 
        box-shadow: 0 1px 3px rgba(0,0,0,0.25);
        border: 1px solid rgba(255,255,255,0.06);
        overflow: hidden;
    }
    .log-card.log-info { border-left: 4px solid #2ecc71; background: linear-gradient(90deg, rgba(46, 204, 113, 0.12) 0%, rgba(26, 29, 36, 0.6) 100%); }
    .log-card.log-warning { border-left: 4px solid #f1c40f; background: linear-gradient(90deg, rgba(241, 196, 15, 0.14) 0%, rgba(26, 29, 36, 0.6) 100%); }
    .log-card.log-error { border-left: 4px solid #e74c3c; background: linear-gradient(90deg, rgba(231, 76, 60, 0.15) 0%, rgba(26, 29, 36, 0.6) 100%); }
    
    .log-card-header { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.35rem; }
    .log-card-time { color: #8899a6; font-family: monospace; font-size: 0.72rem; }
    .log-card-level { 
        display: inline-block; padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
    }
    .log-card-level.info { background: rgba(46, 204, 113, 0.35); color: #2ecc71; }
    .log-card-level.warning { background: rgba(241, 196, 15, 0.35); color: #f1c40f; }
    .log-card-level.error { background: rgba(231, 76, 60, 0.35); color: #e74c3c; }
    .log-card-rid { font-family: monospace; font-size: 0.7rem; color: #6c757d; }
    .log-card-logger { font-size: 0.7rem; color: #8899a6; }
    .log-card-msg { color: #e6e8eb; line-height: 1.4; word-break: break-word; }
    .log-card-extra { margin-top: 0.4rem; padding-top: 0.35rem; border-top: 1px solid rgba(255,255,255,0.06); font-size: 0.72rem; color: #8899a6; font-family: monospace; }
    
    /* Fila de filtros */
    .log-filters-row { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
    
    .banner-error { padding: 0.75rem 1rem; background: rgba(231, 76, 60, 0.3); border-radius: 8px; margin-bottom: 1rem; }
</style>
""",
    unsafe_allow_html=True,
)


def render_sidebar():
    st.sidebar.title("⚙️ Configuración")
    st.sidebar.markdown("---")

    # Selector de cliente
    keys = list(CONFIGS.keys())
    idx = keys.index(st.session_state.client_key) if st.session_state.client_key in keys else 0
    new_client = st.sidebar.radio("Cliente", options=keys, index=idx, format_func=lambda x: x)
    if new_client != st.session_state.client_key:
        st.session_state.client_key = new_client
        try:
            st.session_state.orchestrator = get_orchestrator(new_client)
            st.session_state.orchestrator.reset_conversation()
        except Exception as e:
            st.sidebar.error(str(e))
        st.session_state.messages = []
        st.rerun()

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Nueva conversación"):
        if st.session_state.orchestrator:
            st.session_state.orchestrator.reset_conversation()
        st.session_state.messages = []
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("Estado")
    api_ok = check_api_health()
    llm_ok = check_ollama_health()
    st.sidebar.markdown("🟢 API: Online" if api_ok else "🔴 API: Offline")
    st.sidebar.markdown("🟢 LLM: Online" if llm_ok else "🔴 LLM: Offline")

    cfg = st.session_state.orchestrator.client_config if st.session_state.orchestrator else {}
    st.sidebar.markdown("---")
    st.sidebar.caption("Cliente actual")
    st.sidebar.write("**Nombre:**", cfg.get("client_name", "—"))
    st.sidebar.write("**Idioma:**", cfg.get("language", "—"))
    st.sidebar.write("**Tono:**", cfg.get("tone", "—"))

    return api_ok, llm_ok


def _log_entry_matches_endpoint(entry: dict, endpoint_filter: str) -> bool:
    """True si el log corresponde al endpoint seleccionado (path o logger)."""
    if endpoint_filter == "All":
        return True
    path = (entry.get("extra") or {}).get("path") or ""
    logger_name = entry.get("logger") or ""
    if endpoint_filter == "/shipments":
        return "/shipments" in path or "shipments" in logger_name
    if endpoint_filter == "/tickets":
        return "/tickets" in path or "tickets" in logger_name
    if endpoint_filter == "/logs":
        return "/logs" in path or "logs" in logger_name
    return True


def _format_log_time(ts_iso: str) -> str:
    """Formato corto para mostrar en card: HH:MM:SS"""
    if not ts_iso:
        return "—"
    try:
        dt = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts_iso[:19] if len(ts_iso) >= 19 else ts_iso


def _render_log_card(entry: dict) -> str:
    """Genera HTML de una card de log.

    El esqueleto (div/span/clases) se mantiene como HTML, pero TODO el contenido
    proveniente de los logs se escapa con html.escape para evitar inyección o
    que se vean tags crudos en la UI.
    """
    level = (entry.get("level") or "INFO").upper()
    if level == "WARNING":
        level_class = "warning"
    elif level == "ERROR":
        level_class = "error"
    else:
        level_class = "info"

    # Valores crudos desde el log
    ts_raw = _format_log_time(entry.get("timestamp") or "")
    rid_raw = entry.get("request_id") or ""
    logger_raw = entry.get("logger") or ""
    msg_raw = entry.get("message") or ""
    extra = entry.get("extra") or {}

    # Construir partes de extra en crudo
    extra_parts_raw = []
    if extra.get("method"):
        extra_parts_raw.append(f"{extra['method']} {extra.get('path', '')}")
    if extra.get("status_code") is not None:
        extra_parts_raw.append(f"→ {extra['status_code']}")
    if extra.get("duration_ms") is not None:
        extra_parts_raw.append(f"{extra['duration_ms']} ms")
    if rid_raw:
        extra_parts_raw.append(f"req:{rid_raw}")

    # Escapar contenido dinámico antes de interpolar en la plantilla HTML
    ts = html.escape(str(ts_raw), quote=False)
    rid = html.escape(str(rid_raw), quote=False)
    logger_name = html.escape(str(logger_raw), quote=False)
    msg = html.escape(str(msg_raw), quote=False)
    extra_html = html.escape(" · ".join(str(p) for p in extra_parts_raw), quote=False) if extra_parts_raw else ""

    rid_span = f'<span class="log-card-rid">#{rid}</span>' if rid_raw else ""
    logger_span = f'<span class="log-card-logger">{logger_name}</span>' if logger_raw else ""
    extra_block = f'<div class="log-card-extra">{extra_html}</div>' if extra_html else ""
    return f'''
    <div class="log-card log-{level_class}">
        <div class="log-card-header">
            <span class="log-card-time">{ts}</span>
            <span class="log-card-level {level_class}">{level}</span>
            {rid_span}
            {logger_span}
        </div>
        <div class="log-card-msg">{msg}</div>
        {extra_block}
    </div>
    '''


def render_logs_panel(logs: list):
    """Panel de logs con header, badges, filtros y cards por entrada."""
    # Header: título + badge count + último refresh
    n_entries = len(logs or [])
    last_refresh = st.session_state.last_logs_refresh
    refresh_str = last_refresh.strftime("%H:%M:%S") if last_refresh else "—"
    st.markdown(
        f'<div class="log-panel-header">'
        f'<span class="log-panel-title">📋 Activity Log</span>'
        f'<span class="log-badge">{n_entries} entries</span>'
        f'<span class="log-refresh-ts">Refresh: {refresh_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Filtros en fila: checkboxes inline, selectbox endpoint, slider minutos
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        show_info = st.checkbox("INFO", value=st.session_state.show_info, key="cb_info")
        show_warning = st.checkbox("WARN", value=st.session_state.show_warning, key="cb_warn")
        show_error = st.checkbox("ERROR", value=st.session_state.show_error, key="cb_err")
    with c2:
        endpoint_opts = ["All", "/shipments", "/tickets", "/logs"]
        idx = endpoint_opts.index(st.session_state.filter_endpoint) if st.session_state.filter_endpoint in endpoint_opts else 0
        endpoint = st.selectbox("Endpoint", options=endpoint_opts, index=idx, key="sb_endpoint")
    with c3:
        minutes = st.select_slider(
            "Últimos N min",
            options=[1, 5, 15, 30],
            value=st.session_state.filter_minutes,
            key="slider_min",
        )
    with c4:
        if st.button("Limpiar logs", key="btn_clear_logs"):
            st.session_state.logs_cleared_at = datetime.now(timezone.utc)
            st.session_state.logs = []
            st.session_state.logs_cleared = True
            st.rerun()

    st.session_state.show_info = show_info
    st.session_state.show_warning = show_warning
    st.session_state.show_error = show_error
    st.session_state.filter_endpoint = endpoint
    st.session_state.filter_minutes = minutes

    # Aplicar filtros
    filtered = []
    for entry in (logs or []):
        level = (entry.get("level") or "INFO").upper()
        if level == "INFO" and not show_info:
            continue
        if level == "WARNING" and not show_warning:
            continue
        if level == "ERROR" and not show_error:
            continue
        if not _log_entry_matches_endpoint(entry, endpoint):
            continue
        filtered.append(entry)

    # Mostrar últimas 100 como cards
    to_show = (filtered or [])[-100:]
    for entry in to_show:
        st.markdown(_render_log_card(entry), unsafe_allow_html=True)


def main():
    api_ok, llm_ok = render_sidebar()

    if not api_ok:
        st.error("⚠️ API no disponible. Ejecuta: `uvicorn api.main:app --port 8000`")
    if not llm_ok:
        st.error("⚠️ LLM no disponible. Ejecuta: `ollama serve`")

    # Inicializar orchestrator si no existe
    if st.session_state.orchestrator is None:
        try:
            st.session_state.orchestrator = get_orchestrator(st.session_state.client_key)
        except Exception as e:
            st.error(f"No se pudo cargar el agente: {e}")
            st.stop()

    # Layout: 70% chat, 30% logs
    col_chat, col_logs = st.columns([7, 3])

    # Actualizar logs desde API (filtro "últimos N minutos")
    since_dt = datetime.now(timezone.utc) - timedelta(minutes=st.session_state.filter_minutes)
    st.session_state.logs_raw = fetch_logs(limit=200, since=since_dt.isoformat())
    st.session_state.last_logs_refresh = datetime.now(timezone.utc)
    # Filtrar por logs_cleared_at: solo mostrar logs posteriores al clear
    if st.session_state.logs_cleared_at is not None:
        try:
            cutoff = st.session_state.logs_cleared_at
            filtered = []
            for entry in st.session_state.logs_raw:
                ts_str = entry.get("timestamp") or ""
                if ts_str:
                    try:
                        # ISO con Z o +00:00
                        entry_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if entry_dt.tzinfo is None:
                            entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                        if cutoff.tzinfo is None and entry_dt.tzinfo:
                            cutoff = cutoff.replace(tzinfo=timezone.utc)
                        if entry_dt >= cutoff:
                            filtered.append(entry)
                    except Exception:
                        filtered.append(entry)
                else:
                    filtered.append(entry)
            st.session_state.logs = filtered
        except Exception:
            st.session_state.logs = st.session_state.logs_raw
    else:
        st.session_state.logs = st.session_state.logs_raw

    with col_chat:
        st.title("🚚 Logistics Agent")
        st.markdown("---")

        # Contenedor de mensajes (arriba); input abajo para que sea como chat real
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                metadata = msg.get("metadata") or {}
                avatar = "👤" if role == "user" else "🤖"
                with st.chat_message(role, avatar=avatar):
                    st.markdown(content)
                    if role == "assistant" and metadata:
                        with st.expander("🔧 Detalles técnicos"):
                            st.write("**Intent:**", metadata.get("intent", "—"))
                            st.write("**Confidence:**", metadata.get("confidence", "—"))
                            tool = metadata.get("tool") or {}
                            st.write("**Tool:**", tool.get("name", "none"))
                            if tool.get("args"):
                                st.json(tool.get("args"))
                            if metadata.get("tool_result") is not None:
                                st.write("**Respuesta API:**")
                                st.json(metadata.get("tool_result"))
                            if metadata.get("duration_ms") is not None:
                                st.write("**Duración:**", f"{metadata['duration_ms']} ms")

        # Input al final de la columna (como chat real)
        prompt = st.chat_input("Escribe tu mensaje...")
        if prompt:
            st.session_state.messages.append({"role": "user", "content": prompt, "metadata": None})
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Procesando..."):
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        response = loop.run_until_complete(
                            st.session_state.orchestrator.process_message(prompt)
                        )
                        loop.close()
                    except Exception as e:
                        response = {
                            "user_message": f"Error: {e}. Intente de nuevo.",
                            "intent": "other",
                            "confidence": 0,
                            "tool": {"name": "none", "args": {}},
                            "meta": None,
                        }
                meta = response.get("meta") or {}
                metadata = {
                    "intent": response.get("intent"),
                    "confidence": response.get("confidence"),
                    "tool": response.get("tool"),
                    "tool_result": meta.get("tool_result"),
                    "duration_ms": meta.get("duration_ms"),
                }
                st.markdown(response.get("user_message", ""))
                with st.expander("🔧 Detalles técnicos"):
                    st.write("**Intent:**", metadata.get("intent", "—"))
                    st.write("**Confidence:**", metadata.get("confidence", "—"))
                    st.write("**Tool:**", (metadata.get("tool") or {}).get("name", "none"))
                    if (metadata.get("tool") or {}).get("args"):
                        st.json((metadata.get("tool") or {}).get("args"))
                    if metadata.get("tool_result") is not None:
                        st.write("**Respuesta API:**")
                        st.json(metadata.get("tool_result"))
                    if metadata.get("duration_ms") is not None:
                        st.write("**Duración:**", f"{metadata['duration_ms']} ms")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response.get("user_message", ""),
                    "metadata": metadata,
                })

    with col_logs:
        render_logs_panel(st.session_state.logs)


if __name__ == "__main__":
    main()
