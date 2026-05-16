"""News search phase UI — extracted from wechat_panel.py."""

from __future__ import annotations

import streamlit as st

from src.wechat_service import (
    max_articles_for_performance,
    run_digest_stage,
    run_discussion_stage,
    run_enrich_stage,
    run_search_stage,
)


# ── Streamlit utilities (shared with wechat_panel) ────────────────────


def _rerun_app():
    try:
        st.rerun(scope="fragment")
    except Exception:
        st.rerun()


def _queue_wechat_notice(message: str, level: str = "success"):
    st.session_state.wechat_notice = {
        "message": message,
        "level": level,
    }


# ── Phase state machine ───────────────────────────────────────────────

_PHASE_ORDER = ["searched", "enriched", "digested", "done"]
_PHASE_LABELS = {
    "searched": "搜索结果已获取",
    "enriched": "正文读取已完成",
    "digested": "摘要已生成",
    "done": "群聊已生成",
}
_PHASE_ICONS = {
    "done": "✅",
    "digested": "✅",
    "enriched": "✅",
    "searched": "✅",
}


# ── News search (stage 1) ────────────────────────────────────────────


def run_news_search(query_text: str, read_articles: bool = True) -> None:
    """Run stage 1 (search only) and set phase; does NOT write to group."""
    news_items = run_search_stage(query_text)
    st.session_state.wechat_news_items = news_items
    st.session_state.wechat_news_query_text = query_text
    st.session_state.wechat_news_read_articles = read_articles
    st.session_state.wechat_news_phase = "searched"
    # Clear any stale digest/discussion state from a previous round
    st.session_state.wechat_news_digest = ""
    st.session_state.wechat_news_source_block = ""
    st.session_state.wechat_news_coverage = {}
    st.session_state.wechat_news_warnings = []
    _rerun_app()


# ── Phase progression UI ──────────────────────────────────────────────


def render_news_round_phases():
    """Render phase indicators + action buttons for the search→discuss pipeline."""
    phase = st.session_state.get("wechat_news_phase")
    if not phase:
        return

    items = st.session_state.get("wechat_news_items", [])
    query_text = st.session_state.get("wechat_news_query_text", "")
    read_articles = st.session_state.get("wechat_news_read_articles", True)
    digest = st.session_state.get("wechat_news_digest", "")

    current_idx = _PHASE_ORDER.index(phase) if phase in _PHASE_ORDER else -1

    # Phase progress indicators
    for idx, ph in enumerate(_PHASE_ORDER):
        label = _PHASE_LABELS[ph]
        if idx <= current_idx:
            st.success(f"{_PHASE_ICONS[ph]} {label}")
        else:
            st.caption(f"⏳ {label}")

    # Search results list (shown once available)
    if items:
        with st.expander(
            f"搜索结果 ({len(items)} 条)",
            expanded=phase in ("searched", "enriched"),
        ):
            for idx, item in enumerate(items[:10], start=1):
                article_status = str(item.get("article_status", ""))
                icon = " \U0001f4d6" if "正文已读" in article_status else " \U0001f4f0"
                st.caption(
                    f"{idx}.{icon} {item.get('title', '')} | {item.get('source', '')} | {item.get('published_at', '')}"
                )

    # Digest display
    if digest and phase in ("digested", "done"):
        coverage = st.session_state.get("wechat_news_coverage", {})
        warnings_data = st.session_state.get("wechat_news_warnings", [])
        with st.expander("新闻摘要", expanded=True):
            if coverage:
                total = coverage.get("total", 0)
                with_text = coverage.get("with_text", 0)
                if total > 0:
                    pct = int(with_text / total * 100)
                    color = "green" if pct >= 50 else "red"
                    st.markdown(f":{color}[正文覆盖率 {with_text}/{total} ({pct}%)]")
            for w in warnings_data:
                st.warning(w)
            st.markdown(digest)

    # Phase action buttons
    if phase == "searched" and read_articles:
        if st.button("\U0001f4d6 读取正文", key="phase_enrich", use_container_width=True):
            max_articles = max_articles_for_performance(
                st.session_state.runtime_modes.performance_mode
            )
            with st.spinner("正在读取新闻正文..."):
                try:
                    enriched = run_enrich_stage(
                        items,
                        max_articles=max_articles,
                        query_text=query_text,
                    )
                    st.session_state.wechat_news_items = enriched
                    st.session_state.wechat_news_phase = "enriched"
                    _rerun_app()
                except Exception as exc:
                    st.warning(f"正文读取失败：{exc}")

    if phase in ("searched", "enriched"):
        btn_label = "\U0001f4dd 生成摘要"
        if phase == "searched" and not read_articles:
            btn_label = "\U0001f4dd 直接生成摘要（跳过正文读取）"
        if st.button(btn_label, key="phase_digest", use_container_width=True):
            with st.spinner("正在生成摘要..."):
                try:
                    digest_result, source_block, coverage, warnings = run_digest_stage(
                        items,
                        query_text=query_text,
                        performance_mode=st.session_state.runtime_modes.performance_mode,
                        selected_model=st.session_state.model_profile,
                    )
                    st.session_state.wechat_news_digest = digest_result
                    st.session_state.wechat_news_source_block = source_block
                    st.session_state.wechat_news_coverage = coverage
                    st.session_state.wechat_news_warnings = warnings
                    st.session_state.wechat_news_phase = "digested"
                    _rerun_app()
                except Exception as exc:
                    st.warning(f"摘要生成失败：{exc}")

    if phase == "digested":
        if st.button("\U0001f4ac 生成群聊讨论", key="phase_discuss", use_container_width=True):
            with st.spinner("正在生成群聊讨论..."):
                try:
                    discussion, group_content = run_discussion_stage(
                        digest=st.session_state.wechat_news_digest,
                        interaction_mode=st.session_state.interaction_mode,
                        performance_mode=st.session_state.runtime_modes.performance_mode,
                        selected_model=st.session_state.model_profile,
                        source_block=st.session_state.wechat_news_source_block,
                        session_id=st.session_state.session_id,
                    )
                    st.session_state.wechat_messages = group_content
                    st.session_state.wechat_news_phase = "done"
                    _queue_wechat_notice(f"已围绕「{query_text}」拉起群聊讨论。")
                    _rerun_app()
                except Exception as exc:
                    st.warning(f"群聊讨论生成失败：{exc}")


# ── Legacy digest display ─────────────────────────────────────────────


def render_news_digest():
    """Render a legacy news digest (from the old monolithic flow)."""
    digest = st.session_state.get("wechat_news_digest", "").strip()
    items = st.session_state.get("wechat_news_items", [])
    if not digest:
        return

    coverage = st.session_state.get("wechat_news_coverage", {})
    warnings_data = st.session_state.get("wechat_news_warnings", [])
    elapsed_ms = st.session_state.get("wechat_news_elapsed_ms", 0)

    with st.expander("今日新闻摘要", expanded=False):
        if coverage:
            total = coverage.get("total", 0)
            with_text = coverage.get("with_text", 0)
            if total > 0:
                pct = int(with_text / total * 100)
                color = "green" if pct >= 50 else "red"
                st.markdown(
                    f":{color}[正文覆盖率 {with_text}/{total} ({pct}%)] "
                    f"| 耗时 {elapsed_ms}ms"
                )

        if warnings_data:
            for w in warnings_data:
                st.warning(w)

        if items:
            for idx, item in enumerate(items[:10], start=1):
                article_status = str(item.get("article_status", ""))
                icon = (
                    " :page_facing_up:"
                    if "正文已读" in article_status
                    else " :newspaper:"
                )
                st.caption(
                    f"{idx}.{icon} {item.get('title', '')} | {item.get('source', '')} | {item.get('published_at', '')}"
                )
        st.markdown(digest)
