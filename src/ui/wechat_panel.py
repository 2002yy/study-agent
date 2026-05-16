from __future__ import annotations

from functools import lru_cache
import hashlib
import html as html_mod
import re

import streamlit as st

from src.mode_manager import (
    load_runtime_modes,
    run_with_confirm_write,
    update_interaction_mode,
    update_wechat_join_state,
)
from src.session_logger import (
    set_wechat_interactive,
    set_wechat_memory_candidates,
    set_interaction_mode,
    set_wechat_status,
    set_wechat_unread_cleared,
)
from src.ui.wechat_bubble import format_wechat_bubbles
from src.ui.wechat_news_panel import (
    _queue_wechat_notice,
    _rerun_app,
    render_news_digest,
    render_news_round_phases,
    run_news_search,
)
from src.wechat_generator import (
    generate_interactive_wechat_reply_stream,
    generate_wechat_opening,
    normalize_interactive_wechat_reply,
)
from src.wechat_state import (
    append_interactive_group_reply,
    append_user_group_message,
    count_wechat_messages,
    has_wechat_group_started,
    has_wechat_unread,
    mark_wechat_read,
    read_wechat_group,
    read_wechat_state,
    read_wechat_unread,
    reset_wechat_group,
    search_wechat,
    start_wechat_group_with_opening,
    summarize_wechat,
)
from src.wechat_memory import (
    append_manual_memory_candidate,
    apply_candidate_to_memory,
    extract_memory_candidates,
    save_candidates,
)
from src.constants import ATMOS_LABELS, PERF_LABELS, ROLE_LABELS


def _apply_mark_wechat_read(session_id: str, session_state) -> None:
    mark_wechat_read()
    set_wechat_unread_cleared(session_id)
    session_state.wechat_messages = read_wechat_group()


def _apply_new_wechat_group(session_state) -> None:
    reset_wechat_group()
    session_state.wechat_messages = None
    session_state.wechat_pending_input = None
    session_state.wechat_news_items = []
    session_state.wechat_news_digest = ""


def _rerun_wechat_fragment():
    _rerun_app()


def _render_wechat_notice():
    notice = st.session_state.pop("wechat_notice", None)
    if not notice:
        return

    level = notice.get("level", "success")
    message = notice.get("message", "")

    if level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    elif level == "info":
        st.info(message)
    else:
        st.success(message)


def _active_wechat_content() -> tuple[str, str]:
    if st.session_state.get("wechat_messages"):
        return st.session_state.wechat_messages, "thread"

    group = read_wechat_group()
    unread = read_wechat_unread()
    state = read_wechat_state()

    if state["mode"] == "interactive_group" and group:
        return group, "thread"
    if has_wechat_unread():
        return unread, "unread"
    return group, "thread"


@lru_cache(maxsize=32)
def _format_wechat_bubbles_cached(content: str) -> str:
    return format_wechat_bubbles(content)


def _render_wechat_stream(target, content: str):
    if content and any(
        name in content
        for name in ["【三月七】", "【刻晴】", "【纳西妲】", "【流萤】", "【用户】"]
    ):
        target.markdown(_format_wechat_bubbles_cached(content), unsafe_allow_html=True)
        return
    if content:
        target.markdown(content)
        return
    target.info(
        "当前还没有新的群聊内容。只有当你点击按钮或发送消息时，才会触发群聊互动。"
    )


def _render_wechat_tools(content: str):
    with st.expander("群聊工具", expanded=False):
        st.caption(f"当前可见消息数：{count_wechat_messages(content)}")
        keyword = st.text_input(
            "搜索群聊", key="wc_search", placeholder="输入关键词..."
        )
        if keyword:
            results = search_wechat(keyword)
            for item in results[:5]:
                st.caption(f"**{item['speaker']}**")
                st.text(item["text"][:100])

        if st.button("生成群聊摘要", key="wechat_summary"):
            st.text(summarize_wechat())


def _commit_interaction_mode(choice: str):
    if choice != st.session_state.interaction_mode:
        st.session_state.interaction_mode = choice
        update_interaction_mode(choice)
        set_interaction_mode(st.session_state.session_id, choice)


def _render_wechat_memory_actions(content: str):
    if not st.session_state.get("wechat_memory_enabled"):
        return

    if st.button("提取微信群记忆候选", key="extract_wechat_memory"):
        with st.spinner("正在提取记忆候选..."):
            candidates = extract_memory_candidates(
                wechat_content=content,
                memory_bundle=st.session_state.memory_bundle,
            )
        has_any = any(candidates.get(k) for k in candidates)
        if has_any:
            save_candidates(candidates)
            set_wechat_memory_candidates(st.session_state.session_id, "generated")
            st.success("记忆候选已提取")
            st.session_state.wechat_memory_candidates = candidates
        else:
            st.warning("未提取到候选内容")

    if st.session_state.get("wechat_memory_candidates"):
        with st.expander("记忆候选", expanded=False):
            candidates = st.session_state.wechat_memory_candidates
            for key in [
                "summary_candidates",
                "progress_candidates",
                "current_focus_candidates",
                "learner_profile_candidates",
                "revision_notes_candidates",
                "session_archive_candidates",
            ]:
                items = candidates.get(key, [])
                if not items:
                    continue
                st.caption(f"**{key}** ({len(items)} 条)")
                for idx, item in enumerate(items):
                    st.text(f"[{idx}] {item.get('content', '')[:80]}")
                    if st.button(f"确认写入 {key}[{idx}]", key=f"apply_{key}_{idx}"):
                        modes = load_runtime_modes()
                        if modes.safe_mode:
                            st.warning("当前为安全模式，禁止写入长期记忆。")
                        elif modes.memory_mode == "locked":
                            st.warning("长期记忆已锁定，禁止写入。")
                        else:
                            result = run_with_confirm_write(
                                lambda k=key, i=idx: apply_candidate_to_memory(
                                    k, i, st.session_state.interaction_mode
                                )
                            )
                            if result:
                                st.success(f"已写入 {result}")
                            else:
                                st.warning("写入失败")


def _render_citation_tools(content: str):
    with st.expander("引用到记忆候选", expanded=False):
        blocks = re.findall(r"【(.+?)】\s*(.+?)(?=\n【|\Z)", content, re.DOTALL)
        if not blocks:
            st.caption("当前没有可引用的角色消息。")
            return
        cited_map = st.session_state.setdefault("wechat_cited_items", {})
        st.caption(
            "把你觉得有长期价值的群聊片段一键加入候选。已加入的条目会在这里直接标记出来。"
        )
        display_cols = st.columns(2)
        for idx, (speaker, msg) in enumerate(blocks):
            text = msg.strip()[:120]
            safe_speaker = html_mod.escape(speaker)
            safe_text = html_mod.escape(text)
            cite_key = hashlib.md5(f"{speaker}:{text}".encode("utf-8")).hexdigest()
            already_cited = bool(cited_map.get(cite_key))
            with display_cols[idx % 2]:
                status_badge = (
                    '<span class="wechat-cite-badge added">已加入</span>'
                    if already_cited
                    else '<span class="wechat-cite-badge">可加入</span>'
                )
                st.markdown(
                    f"""
                    <div class="wechat-cite-card{" added" if already_cited else ""}">
                        <div class="wechat-cite-head">
                            <div class="wechat-cite-meta">[{safe_speaker}]</div>
                            <div class="wechat-cite-status">{status_badge}</div>
                        </div>
                        <div class="wechat-cite-text">{safe_text}...</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if already_cited:
                    st.button(
                        "已加入",
                        key=f"cite_done_{idx}",
                        disabled=True,
                        use_container_width=True,
                    )
                elif st.button("加入候选", key=f"cite_{idx}", use_container_width=True):
                    candidates = append_manual_memory_candidate(speaker, text)
                    cited_map[cite_key] = {
                        "speaker": speaker,
                        "text": text,
                    }
                    st.success(f"已将 [{speaker}] 这条消息加入记忆候选")
                    st.session_state.wechat_memory_candidates = candidates


def _stream_pending_reply(content_placeholder):
    pending_input = st.session_state.get("wechat_pending_input")
    if not pending_input:
        return

    base_content = read_wechat_group()
    live_note = st.empty()
    live_note.caption("她们正在输入...")
    reply = ""

    try:
        stream_result = generate_interactive_wechat_reply_stream(
            pending_input,
            relationship_mode=st.session_state.interaction_mode,
        )
        for chunk in stream_result[0]:
            reply += chunk
            preview = base_content if not reply else base_content + "\n\n" + reply
            _render_wechat_stream(content_placeholder, preview)
    except Exception as exc:
        live_note.empty()
        st.session_state.wechat_pending_input = None
        st.error(str(exc))
        return

    live_note.empty()
    if reply.strip():
        reply = normalize_interactive_wechat_reply(reply)
        append_interactive_group_reply(reply)
        if stream_result[1]:
            update_wechat_join_state(
                user_has_joined=True,
                first_reaction_done=True,
                mode="interactive_group",
            )
        set_wechat_interactive(st.session_state.session_id, "generated")
    st.session_state.wechat_messages = read_wechat_group()
    st.session_state.wechat_pending_input = None
    _rerun_wechat_fragment()


def _render_opening_setup():
    st.markdown(
        """
        <div class="wechat-opening-card">
            <div class="wechat-opening-title">先选一个群聊氛围</div>
            <div class="wechat-opening-desc">
                这一轮开场会按你当前的角色、氛围和性能模式生成。生成完成后，群里会先有一轮她们彼此之间的对话，不会提前知道你要来。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    opening_options = ["standard", "warm", "close"]
    choice = st.radio(
        "开场氛围",
        options=opening_options,
        index=opening_options.index(
            st.session_state.get("wechat_opening_choice", "standard")
        ),
        horizontal=True,
        format_func=lambda x: ATMOS_LABELS.get(x, x),
        key="wechat_opening_atmosphere_radio",
    )
    st.session_state.wechat_opening_choice = choice

    runtime_modes = st.session_state.runtime_modes
    st.caption(
        f"当前角色：{ROLE_LABELS.get(st.session_state.current_role, st.session_state.current_role)} · "
        f"当前性能：{PERF_LABELS.get(runtime_modes.performance_mode, runtime_modes.performance_mode)} · "
        f"当前氛围：{ATMOS_LABELS.get(choice, choice)}"
    )

    cols = st.columns(2)
    with cols[0]:
        if st.button(
            "生成群聊开场", key="generate_wechat_opening", use_container_width=True
        ):
            _commit_interaction_mode(choice)
            with st.spinner("正在生成开场..."):
                opening = generate_wechat_opening(
                    role_hint=st.session_state.current_role,
                    relationship_mode=choice,
                    performance_mode=runtime_modes.performance_mode,
                    selected_model=st.session_state.model_profile,
                )
            start_wechat_group_with_opening(opening)
            st.session_state.wechat_messages = read_wechat_group()
            _queue_wechat_notice("群聊开场已生成。")
            _rerun_app()
    with cols[1]:
        if st.button(
            "聊最近新闻", key="news_round_from_opening", use_container_width=True
        ):
            _commit_interaction_mode(choice)
            with st.spinner("正在搜索今日新闻..."):
                try:
                    run_news_search("最新新闻 when:1d")
                except Exception as exc:
                    st.warning(f"搜索失败：{exc}")


@st.fragment
def render_wechat_panel():
    st.markdown("### 微信群聊天")
    _render_wechat_notice()
    state = read_wechat_state()
    content, source = _active_wechat_content()
    group_started = has_wechat_group_started()
    set_wechat_status(st.session_state.session_id, state["mode"])
    unread_count = count_wechat_messages(read_wechat_unread())

    top_cols = st.columns([2, 2, 2, 2])
    with top_cols[0]:
        st.caption(f"群聊状态：{state['mode']}")
    with top_cols[1]:
        st.caption(f"未读数量：{unread_count}")
    with top_cols[2]:
        st.caption(f"互动氛围：{st.session_state.interaction_mode}")
    with top_cols[3]:
        st.caption(f"当前视图：{'未读' if source == 'unread' else '完整线程'}")

    action_cols = st.columns([1, 1, 1, 1])
    with action_cols[0]:
        if st.button("刷新群聊", key="refresh_wechat_view", use_container_width=True):
            st.session_state.wechat_messages = None
            _rerun_wechat_fragment()

    with action_cols[1]:
        if st.button("标记已读", key="mark_wechat_read", use_container_width=True):
            _apply_mark_wechat_read(st.session_state.session_id, st.session_state)
            _queue_wechat_notice("当前未读已标记为已读。")
            _rerun_app()

    with action_cols[2]:
        if st.button("新群聊", key="new_wechat_group", use_container_width=True):
            _apply_new_wechat_group(st.session_state)
            _queue_wechat_notice("已开启新群聊。")
            _rerun_app()

    with action_cols[3]:
        if st.button("聊最近新闻", key="news_round_button", use_container_width=True):
            with st.spinner("正在搜索今日新闻..."):
                try:
                    run_news_search("最新新闻 when:1d")
                except Exception as exc:
                    st.warning(f"搜索失败：{exc}")

    with st.form("wechat_web_search_form"):
        search_query = st.text_input(
            "联网查点什么",
            key="wechat_web_search_query",
            placeholder="例如：OpenAI 最近进展 / Godot 4.6 / RTX 5050 笔记本 / 某个技术名词",
        )
        read_articles = st.checkbox(
            "尝试读取正文",
            value=True,
            help="会更准，但可能变慢；部分网站可能无法读取正文。",
        )
        submitted = st.form_submit_button(
            "联网查并拉群聊讨论", use_container_width=True
        )

    if submitted:
        query = search_query.strip()
        if not query:
            st.warning("先输入要查的内容。")
        else:
            with st.spinner("正在搜索..."):
                try:
                    run_news_search(query, read_articles=read_articles)
                except Exception as exc:
                    st.warning(f"联网搜索失败：{exc}")

    content_placeholder = st.empty()
    if not group_started:
        st.caption("也可以直接联网查一个话题，系统会自动拉起一轮群聊讨论。")
        _render_opening_setup()
        return

    _render_wechat_stream(content_placeholder, content)

    if content:
        if st.session_state.get("wechat_news_phase"):
            render_news_round_phases()
        else:
            render_news_digest()
        _render_citation_tools(content)
        _render_wechat_tools(content)
        _render_wechat_memory_actions(content)

    with st.form("wechat_input_form", clear_on_submit=True):
        wechat_user_input = st.text_input(
            "在群里说一句",
            key="wechat_input",
            placeholder="在群里说一句...",
            label_visibility="collapsed",
        )
        send_wechat = st.form_submit_button("发送", use_container_width=True)

    if send_wechat and wechat_user_input and wechat_user_input.strip():
        user_text = wechat_user_input.strip()
        append_user_group_message(user_text)
        st.session_state.wechat_messages = read_wechat_group()
        st.session_state.wechat_pending_input = user_text
        _rerun_wechat_fragment()

    _stream_pending_reply(content_placeholder)
