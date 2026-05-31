from __future__ import annotations

import html

import streamlit as st

from src.after_session import generate_after_session_updates
from src.config import reload_config
from src.health_check import health_report
from src.mode_manager import (
    update_debug_mode,
    update_entry_mode,
    update_interaction_mode,
    update_memory_capture,
    update_performance_mode,
    update_safe_mode,
)
from src.session_logger import (
    save,
    set_after_session_status,
    set_interaction_mode,
    set_wechat_memory_capture,
    set_wechat_unread_cleared,
)
from src.wechat import clear_wechat_unread, count_wechat_messages, read_wechat_state, read_wechat_unread

from src.constants import (
    ATMOS_LABELS,
    ENTRY_LABELS,
    ENTRY_OPTIONS,
    MODE_LABELS,
    MODE_OPTIONS,
    MODEL_LABELS,
    MODEL_OPTIONS,
    PERF_LABELS,
    PERFORMANCE_OPTIONS,
    ROLE_LABELS,
    ROLE_OPTIONS,
)


def _rerun_app():
    st.rerun()


def _settings_changed(
    entry_mode_new: str,
    current_role_new: str,
    current_mode_new: str,
    model_profile_new: str,
    performance_mode_new: str,
    atmosphere_new: str,
    entry_mode_old: str,
    current_role_old: str,
    current_mode_old: str,
    model_profile_old: str,
    performance_mode_old: str,
    atmosphere_old: str,
) -> bool:
    return (
        entry_mode_new != entry_mode_old
        or current_role_new != current_role_old
        or current_mode_new != current_mode_old
        or model_profile_new != model_profile_old
        or performance_mode_new != performance_mode_old
        or atmosphere_new != atmosphere_old
    )


def _switch_to_wechat_entry(unread_content: str, runtime_modes, session_state) -> None:
    session_state.wechat_messages = unread_content
    if runtime_modes.entry_mode != "wechat":
        update_entry_mode("wechat")
        runtime_modes.entry_mode = "wechat"
    session_state.sidebar_notice = "已切换到微信群未读视图"


def _section(title: str):
    st.markdown(f'<div class="sidebar-section-title">{html.escape(title)}</div>', unsafe_allow_html=True)


def _summary_preview() -> str:
    summary = st.session_state.memory_bundle.get("summary.md", "").strip()
    if not summary:
        return "当前还没有可展示的摘要。"
    return summary[:110] + ("..." if len(summary) > 110 else "")


def _focus_preview() -> str:
    focus = st.session_state.memory_bundle.get("current_focus.md", "").strip()
    if not focus:
        return "当前 focus 暂未整理。"
    return focus[:72] + ("..." if len(focus) > 72 else "")


def _stage_preview() -> str:
    progress = st.session_state.memory_bundle.get("progress.md", "").strip()
    summary = st.session_state.memory_bundle.get("summary.md", "").strip()
    for text in [summary, progress]:
        lines = [line.strip().lstrip("- ").strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if line.lower().startswith("v0."):
                return line[:96] + ("..." if len(line) > 96 else "")
    return f"{st.session_state.runtime_modes.current_version} - 当前已同步到最新阶段"


def _task_preview() -> str:
    focus = st.session_state.memory_bundle.get("current_focus.md", "").strip()
    summary = st.session_state.memory_bundle.get("summary.md", "").strip()
    for text in [focus, summary]:
        lines = [
            line.strip().lstrip("- ").strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in lines:
            if len(line) >= 8:
                return line[:96] + ("..." if len(line) > 96 else "")
    return "当前任务会随着 memory 文本同步显示在这里。"


def _mini_state(label: str, value: str):
    st.markdown(
        f"""
        <div class="sidebar-mini-card">
            <div class="sidebar-mini-label">{html.escape(label)}</div>
            <div class="sidebar-mini-value">{html.escape(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar():
    runtime_modes = st.session_state.runtime_modes

    _section("设置")
    with st.form("sidebar_settings_form"):
        entry_mode_new = st.selectbox(
            "聊天入口",
            options=ENTRY_OPTIONS,
            format_func=lambda x: ENTRY_LABELS.get(x, x),
            index=ENTRY_OPTIONS.index(runtime_modes.entry_mode)
            if runtime_modes.entry_mode in ENTRY_OPTIONS
            else 0,
        )
        current_role_new = st.selectbox(
            "角色",
            options=ROLE_OPTIONS,
            format_func=lambda x: ROLE_LABELS.get(x, x),
            index=ROLE_OPTIONS.index(st.session_state.current_role)
            if st.session_state.current_role in ROLE_OPTIONS
            else 0,
        )
        current_mode_new = st.selectbox(
            "模式",
            options=MODE_OPTIONS,
            format_func=lambda x: MODE_LABELS.get(x, x),
            index=MODE_OPTIONS.index(st.session_state.current_mode)
            if st.session_state.current_mode in MODE_OPTIONS
            else 0,
        )
        model_profile_new = st.selectbox(
            "模型",
            options=MODEL_OPTIONS,
            format_func=lambda x: MODEL_LABELS.get(x, x),
            index=MODEL_OPTIONS.index(st.session_state.model_profile)
            if st.session_state.model_profile in MODEL_OPTIONS
            else 0,
            help="选择 Flash（快速）可节省 token。注意：即便选了 Flash，遇到代码/论文/报错/架构等高风险任务时会自动升档到 Pro。",
        )
        performance_mode_new = st.selectbox(
            "性能模式",
            options=PERFORMANCE_OPTIONS,
            format_func=lambda x: PERF_LABELS.get(x, x),
            index=PERFORMANCE_OPTIONS.index(runtime_modes.performance_mode),
        )
        atmosphere_new = st.selectbox(
            "互动氛围",
            options=["standard", "warm", "close"],
            format_func=lambda x: ATMOS_LABELS.get(x, x),
            index=["standard", "warm", "close"].index(st.session_state.interaction_mode),
        )
        apply_settings = st.form_submit_button("应用设置", use_container_width=True)

    if apply_settings:
        anything_changed = _settings_changed(
            entry_mode_new, current_role_new, current_mode_new, model_profile_new,
            performance_mode_new, atmosphere_new,
            runtime_modes.entry_mode, st.session_state.current_role,
            st.session_state.current_mode, st.session_state.model_profile,
            runtime_modes.performance_mode, st.session_state.interaction_mode,
        )

        if entry_mode_new != runtime_modes.entry_mode:
            update_entry_mode(entry_mode_new)
            runtime_modes.entry_mode = entry_mode_new

        st.session_state.current_role = current_role_new
        st.session_state.current_mode = current_mode_new
        st.session_state.model_profile = model_profile_new

        if performance_mode_new != runtime_modes.performance_mode:
            update_performance_mode(performance_mode_new)
            runtime_modes.performance_mode = performance_mode_new
            st.session_state.memory_bundle = {}
            st.session_state.memory_context_mode = ""

        if atmosphere_new != st.session_state.interaction_mode:
            st.session_state.interaction_mode = atmosphere_new
            update_interaction_mode(atmosphere_new)
            set_interaction_mode(st.session_state.session_id, atmosphere_new)

        if anything_changed:
            st.session_state.current_route = {}

        st.session_state.sidebar_notice = "设置已应用"
        _rerun_app()

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    _section("当前状态")
    route = st.session_state.get("current_route", {})
    unread_count = count_wechat_messages(read_wechat_unread())
    wechat_state = read_wechat_state()
    _mini_state("入口", ENTRY_LABELS.get(runtime_modes.entry_mode, runtime_modes.entry_mode))
    _mini_state("版本", runtime_modes.current_version)
    _mini_state("Focus", _focus_preview())
    _mini_state("群聊", f"{wechat_state['mode']} · 未读 {unread_count}")

    with st.expander("更多状态", expanded=False):
        st.caption(
            f"当前解析：{route.get('role', st.session_state.current_role)} / "
            f"{route.get('mode', st.session_state.current_mode)} / "
            f"{route.get('model_profile', st.session_state.model_profile)}"
        )
        st.caption("`debug_mode` 会显示性能计时、路由和调试数据；`safe_mode` 会阻止长期记忆写入等高风险写操作。")
        with st.form("sidebar_runtime_flags_form"):
            debug_new = st.checkbox("debug_mode", value=runtime_modes.debug_mode)
            safe_new = st.checkbox("safe_mode", value=runtime_modes.safe_mode)
            apply_runtime_flags = st.form_submit_button("应用状态开关", use_container_width=True)
        if apply_runtime_flags:
            if debug_new != runtime_modes.debug_mode:
                update_debug_mode(debug_new)
                runtime_modes.debug_mode = debug_new
            if safe_new != runtime_modes.safe_mode:
                update_safe_mode(safe_new)
                runtime_modes.safe_mode = safe_new
            st.session_state.sidebar_notice = "状态开关已应用"
            _rerun_app()

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    _section("记忆")
    if st.button("查看摘要", use_container_width=True):
        st.session_state.show_summary_preview = not st.session_state.get("show_summary_preview", False)

    if st.session_state.memory_error:
        st.warning(st.session_state.memory_error)
    else:
        st.caption(_summary_preview())

    _section("当前阶段")
    st.caption(_stage_preview())

    _section("当前任务")
    st.caption(_task_preview())

    with st.form("sidebar_memory_form"):
        capture_enabled_new = st.checkbox(
            "启用微信群记忆提取",
            value=st.session_state.wechat_memory_enabled,
        )
        apply_memory_flags = st.form_submit_button("应用记忆设置", use_container_width=True)
    if apply_memory_flags:
        if capture_enabled_new != st.session_state.wechat_memory_enabled:
            st.session_state.wechat_memory_enabled = capture_enabled_new
            update_memory_capture(capture_enabled_new)
            set_wechat_memory_capture(
                st.session_state.session_id,
                "enabled" if capture_enabled_new else "disabled",
            )
        st.session_state.sidebar_notice = "记忆设置已应用"
        _rerun_app()

    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)

    _section("操作")
    if st.button("生成课后更新预览", use_container_width=True):
        if st.session_state.messages:
            with st.spinner("生成中..."):
                st.session_state.after_session_updates = generate_after_session_updates(
                    session_messages=st.session_state.messages,
                    memory_bundle=st.session_state.memory_bundle,
                    role=st.session_state.current_role,
                    mode=st.session_state.current_mode,
                    model_profile="pro",
                )
            set_after_session_status(st.session_state.session_id, "preview_generated")
        else:
            st.warning("暂无对话记录。")

    if st.button("结束本轮并保存日志", use_container_width=True):
        if st.session_state.messages:
            path = save(st.session_state.session_id)
            st.success(f"已保存：{path}")
            st.session_state.messages = []
            st.session_state.session_started = False
            st.session_state.after_session_updates = None
            st.session_state.writes_confirmed = False
            st.session_state.wechat_messages = None
        else:
            st.info("暂无对话记录。")

    unread_content = read_wechat_unread()
    has_unread = unread_content and "暂无未读" not in unread_content
    if has_unread and st.button("查看未读消息", use_container_width=True):
        _switch_to_wechat_entry(unread_content, runtime_modes, st.session_state)
        _rerun_app()

    if st.button("清空未读消息", use_container_width=True):
        clear_wechat_unread()
        set_wechat_unread_cleared(st.session_state.session_id)
        st.session_state.wechat_messages = None
        st.session_state.sidebar_notice = "未读消息已清空"
        _rerun_app()

    cols = st.columns(2)
    with cols[0]:
        if st.button("健康检查", use_container_width=True):
            st.session_state.health_report = health_report()
    with cols[1]:
        if st.button("强制刷新", use_container_width=True):
            reload_config()
            st.session_state.memory_bundle = {}
            st.session_state.memory_context_mode = ""
            st.session_state.wechat_messages = None
            st.session_state.health_report = health_report(force_refresh=True)
            st.session_state.sidebar_notice = "配置、记忆与健康状态已刷新"
            _rerun_app()

    if st.session_state.get("health_report"):
        with st.expander("健康报告", expanded=False):
            st.markdown(st.session_state.health_report)

    notice = st.session_state.pop("sidebar_notice", "")
    if notice:
        st.success(notice)

    if runtime_modes.debug_mode:
        with st.expander("调试信息", expanded=False):
            st.json(
                {
                    "entry_mode": runtime_modes.entry_mode,
                    "performance_mode": runtime_modes.performance_mode,
                    "memory_mode": runtime_modes.memory_mode,
                    "route_mode": runtime_modes.route_mode,
                    "wechat_mode": runtime_modes.wechat_mode,
                    "interaction_mode": st.session_state.interaction_mode,
                }
            )
            if st.session_state.get("perf_metrics"):
                st.json(st.session_state.perf_metrics)
