from __future__ import annotations

import streamlit as st

from src.ui.chat_panel import render_chat_panel
from src.ui.wechat_panel import render_wechat_panel


def render_main_panel():
    entry_mode = st.session_state.runtime_modes.entry_mode
    if entry_mode == "single":
        render_chat_panel()
        return
    render_wechat_panel()
