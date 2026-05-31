from __future__ import annotations

import streamlit as st

from src.memory import read_memory_bundle
from src.mode_manager import load_runtime_modes
from src.session_logger import init_session
from src.health_check import _ensure_memory_files


def init_session_state():
    _ensure_memory_files()
    defaults = {
        "messages": [],
        "current_role": "auto",
        "current_mode": "auto",
        "model_profile": "auto",
        "session_started": False,
        "memory_bundle": {},
        "memory_error": "",
        "after_session_updates": None,
        "writes_confirmed": False,
        "wechat_messages": None,
        "wechat_style": "标准",
        "current_route": {},
        "route_lock": None,
        "interaction_mode": "standard",
        "wechat_memory_enabled": False,  # will sync from runtime_modes below
        "runtime_modes": load_runtime_modes(),
        "health_report": "",
        "perf_metrics": {},
        "startup_light_health": [],
        "memory_context_mode": "",
        "pending_user_input": None,
        "show_summary_preview": False,
        "wechat_pending_input": None,
        "wechat_cited_items": {},
        "wechat_opening_choice": "standard",
        "wechat_news_items": [],
        "wechat_news_digest": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Sync wechat_memory_enabled from persisted runtime state
    if st.session_state.get("runtime_modes"):
        st.session_state.wechat_memory_enabled = (
            st.session_state.runtime_modes.memory_capture_enabled
        )

    if "session_id" not in st.session_state:
        st.session_state.session_id = init_session()


def refresh_runtime_state():
    st.session_state.runtime_modes = load_runtime_modes()


def refresh_memory_bundle(context_mode: str | None = None):
    runtime_modes = st.session_state.runtime_modes
    target_context = context_mode or runtime_modes.context_mode
    if (
        st.session_state.get("memory_bundle")
        and st.session_state.get("memory_context_mode") == target_context
    ):
        return

    try:
        st.session_state.memory_bundle = read_memory_bundle(target_context)
        st.session_state.memory_context_mode = target_context
        st.session_state.memory_error = ""
    except Exception as e:
        st.session_state.memory_bundle = {}
        st.session_state.memory_error = str(e)
