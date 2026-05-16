from __future__ import annotations

import html

import streamlit as st

from src.ui.avatar import get_banner_uri, get_html_avatar_uri
from src.wechat import count_wechat_messages, read_wechat_state, read_wechat_unread

from src.constants import (
    ATMOS_ICONS,
    ATMOS_LABELS,
    ENTRY_ICONS,
    ENTRY_LABELS,
    MODE_ICONS,
    MODEL_ICONS,
    MODEL_LABELS,
    PERF_ICONS,
    PERF_LABELS,
    ROLE_ICONS,
    ROLE_LABELS,
    WECHAT_MODE_ICONS,
    WECHAT_MODE_LABELS,
)


def _focus_preview() -> str:
    text = st.session_state.memory_bundle.get("current_focus.md", "").strip()
    if not text:
        return "今天可以从一个最想推进的问题开始，我会陪你把思路慢慢理顺。"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    preview = " ".join(lines[:4])
    return preview[:180] + ("..." if len(preview) > 180 else "")


def _status_card(label: str, value: str, icon: str, accent: str = "") -> str:
    accent_attr = f' data-accent="{accent}"' if accent else ""
    return (
        f'<div class="status-card"{accent_attr}>'
        f'<div class="status-card-icon-wrap"><div class="status-card-icon">{icon}</div></div>'
        f'<div class="status-card-body">'
        f'<div class="status-card-label">{html.escape(label)}</div>'
        f'<div class="status-card-value">{html.escape(value)}</div>'
        f"</div>"
        f"</div>"
    )


def _render_single_cards(runtime_modes, route: dict) -> str:
    resolved_role = route.get("role", st.session_state.current_role)
    resolved_mode = route.get("mode", st.session_state.current_mode)
    resolved_model = route.get("model_profile", st.session_state.model_profile)
    return (
        _status_card("入口", ENTRY_LABELS["single"], ENTRY_ICONS["single"], "primary")
        + _status_card(
            "角色",
            ROLE_LABELS.get(resolved_role, resolved_role),
            ROLE_ICONS.get(resolved_role, "🎭"),
            "secondary",
        )
        + _status_card(
            "模式",
            "自动" if resolved_mode == "auto" else resolved_mode,
            MODE_ICONS.get(resolved_mode, "🧭"),
        )
        + _status_card(
            "模型",
            MODEL_LABELS.get(resolved_model, resolved_model),
            MODEL_ICONS.get(resolved_model, "🧩"),
        )
        + _status_card(
            "性能模式",
            PERF_LABELS.get(runtime_modes.performance_mode, runtime_modes.performance_mode),
            PERF_ICONS.get(runtime_modes.performance_mode, "🎯"),
        )
    )


def _render_wechat_cards(runtime_modes, wechat_state: dict, unread_count: int) -> str:
    return (
        _status_card("入口", ENTRY_LABELS["wechat"], ENTRY_ICONS["wechat"], "primary")
        + _status_card(
            "群聊状态",
            WECHAT_MODE_LABELS.get(wechat_state["mode"], wechat_state["mode"]),
            WECHAT_MODE_ICONS.get(wechat_state["mode"], "🗨️"),
            "secondary",
        )
        + _status_card("未读数量", str(unread_count), "🔔")
        + _status_card(
            "互动氛围",
            ATMOS_LABELS.get(st.session_state.interaction_mode, st.session_state.interaction_mode),
            ATMOS_ICONS.get(st.session_state.interaction_mode, "🌿"),
        )
        + _status_card(
            "性能模式",
            PERF_LABELS.get(runtime_modes.performance_mode, runtime_modes.performance_mode),
            PERF_ICONS.get(runtime_modes.performance_mode, "🎯"),
        )
    )


def _render_compact_wechat_panel(
    runtime_modes,
    role_banner: str,
    role_avatar: str,
    wechat_state: dict,
    unread_count: int,
) -> str:
    return (
        '<div class="focus-panel focus-panel-compact">'
        '<div class="focus-panel-content">'
        '<div class="focus-panel-title">群聊小看板</div>'
        '<div class="focus-panel-copy focus-panel-compact-line">先轻松看一眼状态，再把空间留给真正的聊天内容。</div>'
        '<div class="wechat-compact-grid">'
        f'<div class="wechat-compact-item"><span class="wechat-compact-label">入口</span><span class="wechat-compact-value">{html.escape(ENTRY_LABELS["wechat"])}</span></div>'
        f'<div class="wechat-compact-item"><span class="wechat-compact-label">未读</span><span class="wechat-compact-value">{unread_count}</span></div>'
        f'<div class="wechat-compact-item"><span class="wechat-compact-label">状态</span><span class="wechat-compact-value">{html.escape(WECHAT_MODE_LABELS.get(wechat_state["mode"], wechat_state["mode"]))}</span></div>'
        f'<div class="wechat-compact-item"><span class="wechat-compact-label">氛围</span><span class="wechat-compact-value">{html.escape(ATMOS_LABELS.get(st.session_state.interaction_mode, st.session_state.interaction_mode))}</span></div>'
        "</div>"
        '<div class="focus-panel-tags compact">'
        f'<span class="focus-tag">性能：{html.escape(PERF_LABELS.get(runtime_modes.performance_mode, runtime_modes.performance_mode))}</span>'
        f'<span class="focus-tag">版本：{html.escape(runtime_modes.current_version)}</span>'
        "</div>"
        "</div>"
        '<div class="focus-panel-visual compact">'
        f'<div class="focus-panel-aura" style="background-image:url(\'{role_banner}\');"></div>'
        f'<div class="focus-panel-avatar compact" style="background-image:url(\'{role_avatar}\');"></div>'
        '<div class="focus-panel-ring">✦</div>'
        "</div>"
        "</div>"
    )


def render_status_bar():
    runtime_modes = st.session_state.runtime_modes
    route = st.session_state.get("current_route", {})
    entry_mode = runtime_modes.entry_mode
    resolved_role = route.get("role", st.session_state.current_role)
    visual_role = (
        resolved_role if resolved_role in ROLE_LABELS and resolved_role != "auto" else "march7"
    )
    hero_copy = (
        "欢迎回来，今天想先看看群里的新动静，还是直接聊聊你现在最想推进的事情？"
        if entry_mode == "wechat"
        else "欢迎回来，今天我们继续把手上的学习、项目或论文慢慢往前推进。"
    )
    role_avatar = get_html_avatar_uri(visual_role)
    role_banner = get_banner_uri(visual_role) or get_banner_uri("march7")

    wechat_state = None
    unread_count = 0
    if entry_mode == "wechat":
        wechat_state = read_wechat_state()
        unread_count = count_wechat_messages(read_wechat_unread())

    cards = (
        _render_wechat_cards(runtime_modes, wechat_state, unread_count)
        if entry_mode == "wechat"
        else _render_single_cards(runtime_modes, route)
    )
    focus_html = (
        _render_compact_wechat_panel(
            runtime_modes,
            role_banner,
            role_avatar,
            wechat_state,
            unread_count,
        )
        if entry_mode == "wechat"
        else (
            '<div class="focus-panel">'
            '<div class="focus-panel-content">'
            '<div class="focus-panel-title">当前重点</div>'
            f'<div class="focus-panel-copy">{html.escape(_focus_preview())}</div>'
            '<div class="focus-panel-tags">'
            f'<span class="focus-tag">入口：{html.escape(ENTRY_LABELS.get(entry_mode, entry_mode))}</span>'
            f'<span class="focus-tag">版本：{html.escape(runtime_modes.current_version)}</span>'
            "</div>"
            "</div>"
            '<div class="focus-panel-visual">'
            f'<div class="focus-panel-aura" style="background-image:url(\'{role_banner}\');"></div>'
            f'<div class="focus-panel-avatar" style="background-image:url(\'{role_avatar}\');"></div>'
            '<div class="focus-panel-ring">✦</div>'
            "</div>"
            "</div>"
        )
    )

    html_block = (
        '<div class="hero-shell">'
        '<div class="hero-backdrop"></div>'
        '<div class="hero-head">'
        '<div>'
        '<div class="hero-title">学习伙伴 <span class="hero-wave">👋</span></div>'
        f'<div class="hero-subtitle">{html.escape(hero_copy)}</div>'
        "</div>"
        f'<div class="version-badge">{html.escape(runtime_modes.current_version)}</div>'
        "</div>"
        f'<div class="status-card-grid">{cards}</div>'
        f"{focus_html}"
        "</div>"
    )
    st.markdown(html_block, unsafe_allow_html=True)


def render_model_stats_line():
    from src.model_stats import estimated_cost, get_stats

    stats = get_stats()
    if stats.total_calls == 0:
        return

    st.caption(
        f"Flash: {stats.flash_calls} | Pro: {stats.pro_calls} | "
        f"Router: {stats.llm_router_calls} | "
        f"Last latency: {stats.last_latency:.2f}s | Cost: ￥{estimated_cost():.4f}"
    )

    perf = stats.last_perf or st.session_state.get("perf_metrics", {})
    if st.session_state.runtime_modes.debug_mode and perf:
        st.caption(
            "Perf: "
            f"route {perf.get('route_time', 0):.3f}s | "
            f"memory {perf.get('memory_read_time', 0):.3f}s | "
            f"context {perf.get('context_build_time', 0):.3f}s | "
            f"first token {perf.get('llm_first_token_time', 0):.3f}s | "
            f"llm {perf.get('llm_total_time', 0):.3f}s | "
            f"ui {perf.get('ui_render_time', 0):.3f}s | "
            f"total {perf.get('total_time', 0):.3f}s"
        )

    if st.button("重置统计"):
        from src.model_stats import reset_stats

        reset_stats()
        try:
            st.rerun(scope="fragment")
        except Exception:
            st.rerun()
