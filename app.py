"""Legacy Streamlit compatibility UI.

The supported product runtime is the React frontend backed by FastAPI. This
entrypoint remains only for migration checks.
"""

from __future__ import annotations

import time

import streamlit as st

from src.config import validate
from src.health_check import light_health_report
from src.ui.after_session_panel import render_after_session_panel
from src.ui.chat_panel import render_chat_panel
from src.ui.rag_panel import render_rag_panel
from src.ui.session_state import init_session_state, refresh_memory_bundle, refresh_runtime_state
from src.ui.sidebar import render_sidebar
from src.ui.status_bar import render_model_stats_line, render_status_bar
from src.ui.theme import inject_theme
from src.ui.wechat_panel import render_wechat_panel

st.set_page_config(page_title="学习伙伴 | 个人学习 Agent", layout="wide")
inject_theme()
st.warning(
    "Legacy compatibility UI：主产品入口已迁移到 React（http://127.0.0.1:5173）。"
)


@st.fragment
def render_sidebar_fragment():
    render_sidebar()


@st.fragment
def render_status_fragment():
    render_status_bar()
    render_model_stats_line()


@st.fragment
def render_single_main_fragment():
    render_chat_panel()


@st.fragment
def render_after_session_fragment():
    render_after_session_panel()

app_started = time.perf_counter()
st.title("学习伙伴")

config_errors = validate()
if config_errors:
    for err in config_errors:
        st.warning(f"配置未完成: {err}")

init_session_state()
refresh_runtime_state()
st.session_state.startup_light_health = light_health_report()
refresh_memory_bundle()

if st.session_state.current_role != "auto":
    from src.role_manager import load_role

    with st.popover("查看角色人设"):
        profile = load_role(st.session_state.current_role)
        st.markdown(profile[:800])

with st.sidebar:
    render_sidebar_fragment()
render_status_fragment()

if st.session_state.runtime_modes.entry_mode == "wechat":
    render_wechat_panel()
else:
    render_single_main_fragment()

render_rag_panel()
render_after_session_fragment()

if st.session_state.runtime_modes.debug_mode:
    st.session_state.perf_metrics["total_time"] = time.perf_counter() - app_started
