from __future__ import annotations

import html
import time

import streamlit as st

from src.context_builder import build_messages
from src.llm_client import stream_chat
from src.memory import read_memory_bundle
from src.performance_budget import chat_max_tokens
from src.mode_manager import load_runtime_modes
from src.model_stats import estimate_tokens, record_call, record_perf
from src.perf import PerfTracker, write_perf_log
from src.role_manager import load_role
from src.router import route_request
from src.session_logger import flush_current_session, log
from src.tools.local_knowledge import retrieve_local_knowledge
from src.ui.avatar import get_chat_avatar, get_html_avatar_uri, get_user_avatar
from src.constants import ROLE_LABELS


def _assistant_role_for_message(msg: dict) -> str:
    return msg.get("avatar_role") or st.session_state.get("current_route", {}).get(
        "role", "march7"
    )


def _render_history_message(msg: dict):
    if msg["role"] == "user":
        avatar = get_user_avatar()
    elif msg["role"] == "assistant":
        avatar = get_chat_avatar(_assistant_role_for_message(msg))
    else:
        avatar = None

    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])


_DISPLAY_LABELS = {
    "mode": {"auto": "自动"},
    "model": {
        "auto": "自动",
        "flash": "Flash（快速）",
        "pro": "Pro（高质量）",
    },
    "perf": {"fast": "快速", "standard": "标准", "deep": "深度"},
    "atmos": {"standard": "标准", "warm": "温和", "close": "贴近"},
}


def _display(key: str, value: str) -> str:
    return _DISPLAY_LABELS.get(key, {}).get(value, value)


def _current_focus_preview() -> str:
    text = st.session_state.memory_bundle.get("current_focus.md", "").strip()
    if not text:
        return "当前还没有明确重点，可以直接开始提问，我会先帮你判断最适合从哪里切入。"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    preview = " ".join(lines[:4])
    return preview[:180] + ("..." if len(preview) > 180 else "")


def _summary_preview() -> str:
    text = st.session_state.memory_bundle.get("summary.md", "").strip()
    if not text:
        return "当前还没有可展示的摘要。"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    preview = " ".join(lines[:6])
    return preview[:260] + ("..." if len(preview) > 260 else "")


def _last_milestone() -> str:
    route = st.session_state.get("current_route", {})
    role = ROLE_LABELS.get(route.get("role", ""), "自动")
    perf = _display("perf", st.session_state.runtime_modes.performance_mode)
    mode = _display("mode", route.get("mode", st.session_state.current_mode))
    return f"最近建议：{role} · {mode} · {perf}"


def _progress_snippet() -> tuple[str, str]:
    """Return (recent_progress, next_step) from memory files."""
    summary = st.session_state.memory_bundle.get("summary.md", "")
    progress = st.session_state.memory_bundle.get("progress.md", "")

    recent = ""
    for line in summary.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("• "):
            recent = stripped[2:].strip()
            break

    next_step = ""
    in_next = False
    for line in progress.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 下一步"):
            in_next = True
            continue
        if in_next and stripped.startswith("- "):
            next_step = stripped[2:].strip()
            break
        if in_next and stripped.startswith("## "):
            break

    return recent or "等待首次记录", next_step or "等待首次记录"


def _build_chat_rag_context(user_input: str) -> tuple[str, int, str]:
    if not st.session_state.get("rag_chat_enabled"):
        return "", 0, ""

    top_k = int(st.session_state.get("rag_chat_top_k", 3))
    result = retrieve_local_knowledge(
        user_input,
        top_k=top_k,
        retrieval_mode=st.session_state.get("rag_retrieval_mode", "hybrid"),
    )
    st.session_state.rag_debug = result.debug
    if result.status == "skipped":
        return "", 0, ""
    if result.status == "found":
        st.session_state.rag_results = result.results
        st.session_state.rag_context = result.context
        st.session_state.rag_source_block = result.sources
        return result.context, len(result.results), ""
    if result.status == "not_found":
        st.session_state.rag_results = []
        st.session_state.rag_context = result.context
        st.session_state.rag_source_block = ""
        return result.context, 0, "No relevant local documents"
    return "", 0, result.reason


def _queue_input(prompt: str):
    st.session_state.pending_user_input = prompt
    st.rerun()


def _render_quick_entry(label: str, prompt: str, icon: str, key: str):
    cols = st.columns([0.88, 0.12])
    with cols[0]:
        if st.button(f"{icon}  {label}", key=f"quick_{key}", use_container_width=True):
            _queue_input(prompt)
    with cols[1]:
        st.markdown('<div class="quick-entry-arrow">›</div>', unsafe_allow_html=True)


def _render_welcome_area():
    focus_preview = _current_focus_preview()
    summary_preview = _summary_preview()
    role_for_visual = st.session_state.get("current_route", {}).get("role", "march7")
    role_avatar = get_html_avatar_uri(
        role_for_visual if role_for_visual != "auto" else "march7"
    )
    version = load_runtime_modes().current_version

    recent_progress, next_step = _progress_snippet()

    st.markdown(
        f"""
        <div class="welcome-grid">
            <div class="welcome-card">
                <div class="welcome-title">开始提问吧 👇</div>
                <div class="welcome-copy">你可以这样开始：</div>
                <div class="welcome-focus">
                    <div class="welcome-focus-label">当前重点</div>
                    <div class="welcome-focus-copy">{html.escape(focus_preview)}</div>
                </div>
                <div class="welcome-list-label">快捷入口</div>
            </div>
            <div class="resume-card">
                <div class="resume-head">
                    <div>
                        <div class="resume-title">上次结束位置</div>
                        <div class="resume-list-title">{html.escape(_last_milestone())}</div>
                    </div>
                    <div class="resume-portrait" style="background-image:url('{role_avatar}');"></div>
                </div>
                <div class="resume-copy">
                    • 版本：{html.escape(version)}<br/>
                    • 最近推进：{html.escape(recent_progress)}<br/>
                    • 下次建议：{html.escape(next_step)}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    _render_quick_entry(
        "帮我分析当前 Agent 架构有哪些问题？",
        "帮我分析当前 Agent 架构有哪些问题？",
        "🟣",
        "analyze",
    )
    _render_quick_entry(
        "继续上次的性能优化工作",
        f"继续当前重点：{focus_preview}。请直接带我往下推进。",
        "🔵",
        "continue",
    )
    _render_quick_entry(
        "生成课后更新预览",
        "请根据当前进展，先给我一版课后更新预览。",
        "🩷",
        "summary",
    )

    if st.session_state.get("show_summary_preview"):
        st.markdown(
            f"""
            <div class="welcome-summary-card">
                <div class="welcome-focus-label">当前摘要</div>
                <div class="welcome-focus-copy">{html.escape(summary_preview)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_input_dock():
    route = st.session_state.get("current_route", {})
    runtime_modes = st.session_state.runtime_modes
    current_mode = _display("mode", route.get("mode", st.session_state.current_mode))
    current_model = _display(
        "model", route.get("model_profile", st.session_state.model_profile)
    )
    current_perf = _display("perf", runtime_modes.performance_mode)
    current_atmos = _display("atmos", st.session_state.interaction_mode)

    st.markdown(
        f"""
        <div class="input-dock-meta">
            <div class="input-dock-top">
                <div>
                    <div class="input-dock-title">聊天底栏</div>
                    <div class="input-dock-summary">当前：{html.escape(current_mode)}路由 · {html.escape(current_perf)}</div>
                </div>
                <div class="input-dock-pill">准备开始对话</div>
            </div>
            <div class="input-dock-chips">
                <span class="input-dock-chip"><span class="input-dock-chip-label">模式</span>{html.escape(current_mode)}</span>
                <span class="input-dock-chip"><span class="input-dock-chip-label">模型</span>{html.escape(current_model)}</span>
                <span class="input-dock-chip"><span class="input-dock-chip-label">性能</span>{html.escape(current_perf)}</span>
                <span class="input-dock-chip"><span class="input-dock-chip-label">氛围</span>{html.escape(current_atmos)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _process_user_input(user_input: str, role_prompt: str):
    perf = PerfTracker()
    runtime_modes = st.session_state.runtime_modes
    perf.metrics.performance_mode = runtime_modes.performance_mode
    perf.metrics.context_mode = runtime_modes.context_mode

    st.session_state.messages.append(
        {"role": "user", "content": user_input, "avatar_role": "user"}
    )
    with st.chat_message("user", avatar=get_user_avatar()):
        st.markdown(user_input)

    perf.start("route")
    if st.session_state.route_lock:
        route = {
            "role": st.session_state.route_lock["role"],
            "mode": st.session_state.route_lock["mode"],
            "model_profile": st.session_state.route_lock["model_profile"],
            "reason": "route locked",
            "manual_override": True,
            "confidence": "locked",
            "matched_keywords": [],
            "llm_router_used": False,
        }
    else:
        route = route_request(
            user_input=user_input,
            selected_role=st.session_state.current_role,
            selected_mode=st.session_state.current_mode,
            selected_model=st.session_state.model_profile,
            runtime_modes=runtime_modes,
        )
    perf.stop("route", "route_time")

    route["selected_role"] = st.session_state.current_role
    route["selected_mode"] = st.session_state.current_mode
    route["selected_model"] = st.session_state.model_profile
    st.session_state.current_route = route

    resolved_role = route["role"]
    resolved_mode = route["mode"]
    resolved_model = route["model_profile"]

    perf.start("memory")
    context_mode = runtime_modes.context_mode
    if (
        st.session_state.get("memory_bundle")
        and st.session_state.get("memory_context_mode") == context_mode
    ):
        memory_bundle = st.session_state.memory_bundle
    else:
        memory_bundle = read_memory_bundle(context_mode)
        st.session_state.memory_bundle = memory_bundle
        st.session_state.memory_context_mode = context_mode
    perf.stop("memory", "memory_read_time")

    active_prompt = (
        role_prompt
        if st.session_state.current_role != "auto"
        else load_role(resolved_role)
    )

    perf.start("context")
    rag_context, rag_result_count, rag_warning = _build_chat_rag_context(user_input)
    route["rag_enabled"] = bool(st.session_state.get("rag_chat_enabled"))
    route["rag_result_count"] = rag_result_count
    if rag_warning:
        route["rag_warning"] = rag_warning

    api_messages = build_messages(
        user_input=user_input,
        role_prompt=active_prompt,
        mode=resolved_mode,
        memory_bundle=memory_bundle,
        chat_history=st.session_state.messages[:-1],
        relationship_mode=st.session_state.interaction_mode,
        runtime_modes=runtime_modes,
        context_mode=context_mode,
        rag_context=rag_context,
    )
    perf.stop("context", "context_build_time")

    llm_started = time.perf_counter()
    first_token_at = {"value": None}

    def _mark_first_token():
        if first_token_at["value"] is None:
            first_token_at["value"] = time.perf_counter() - llm_started
            perf.set("llm_first_token_time", first_token_at["value"])

    with st.chat_message("assistant", avatar=get_chat_avatar(resolved_role)):
        try:
            stream = stream_chat(
                api_messages,
                model_profile=resolved_model,
                on_first_token=_mark_first_token,
                max_tokens=chat_max_tokens(runtime_modes.performance_mode),
                task_name="single_chat",
            )
            reply = st.write_stream(stream)
            perf.set("llm_total_time", time.perf_counter() - llm_started)
            perf.metrics.llm_calls = 1 + (1 if route.get("llm_router_used") else 0)
            record_call(
                resolved_model,
                estimate_tokens(str(reply or "")),
                perf.metrics.llm_total_time,
            )
        except Exception as e:
            st.error(str(e))
            reply = None
            perf.set("llm_total_time", time.perf_counter() - llm_started)

    if reply is not None:
        with st.expander("本轮路由结果", expanded=False):
            current_route = st.session_state.current_route
            st.caption(
                f"角色: {ROLE_LABELS.get(current_route['role'], current_route['role'])}"
            )
            st.caption(f"模式: {current_route['mode']}")
            st.caption(f"模型: {current_route['model_profile']}")
            st.caption(
                f"覆盖: {'是' if current_route['manual_override'] else '否（自动）'}"
            )
            st.caption(f"原因: {current_route['reason']}")
            if current_route.get("rag_enabled"):
                st.caption(f"RAG 引用: {current_route.get('rag_result_count', 0)}")
                if current_route.get("rag_warning"):
                    st.caption(f"RAG 状态: {current_route['rag_warning']}")
                elif st.session_state.get("rag_source_block"):
                    with st.expander("RAG 引用来源", expanded=False):
                        st.code(st.session_state.rag_source_block, language="text")

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": reply,
                "avatar_role": resolved_role,
            }
        )
        st.session_state.session_started = True
        log(
            session_id=st.session_state.session_id,
            role=resolved_role,
            mode=resolved_mode,
            model=resolved_model,
            user_input=user_input,
            agent_reply=str(reply),
            memory_enabled=bool(memory_bundle),
            route_info=st.session_state.current_route,
        )
        flush_current_session(
            st.session_state.session_id,
            performance_mode=runtime_modes.performance_mode,
            debug_mode=runtime_modes.debug_mode,
        )

    perf.set("ui_render_time", st.session_state.perf_metrics.get("ui_render_time", 0.0))
    metrics = perf.finish().to_dict()
    record_perf(metrics)
    st.session_state.perf_metrics = metrics
    if runtime_modes.debug_mode:
        write_perf_log(perf.metrics)


@st.fragment
def render_chat_panel():
    render_started = time.perf_counter()
    role_prompt = load_role(
        st.session_state.current_role
        if st.session_state.current_role != "auto"
        else "march7"
    )

    if not st.session_state.messages:
        _render_welcome_area()

    for msg in st.session_state.messages:
        _render_history_message(msg)

    st.session_state.perf_metrics["ui_render_time"] = (
        time.perf_counter() - render_started
    )

    _render_input_dock()

    pending_user_input = st.session_state.pop("pending_user_input", None)
    typed_user_input = st.chat_input("输入你的问题...")
    user_input = typed_user_input or pending_user_input
    if user_input:
        _process_user_input(user_input, role_prompt)
