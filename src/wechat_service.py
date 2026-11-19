from __future__ import annotations

from typing import Callable

from src.mode_manager import update_wechat_join_state
from src.news.digest import format_news_source_block, generate_news_digest
from src.wechat_generator import generate_wechat_news_discussion
from src.wechat_state import (
    append_interactive_group_reply,
    append_system_group_note,
    read_wechat_group,
)


ProgressCallback = Callable[[str], None]


def _compute_article_coverage(news_items: list[dict]) -> dict:
    total = len(news_items)
    with_text = 0
    unresolved_transit = 0
    not_selected = 0
    failed_fetch = 0
    title_only = 0

    for item in news_items:
        status = str(item.get("article_status", ""))
        excerpt = item.get("article_excerpt", "")

        if excerpt or status.startswith("正文已读"):
            with_text += 1
        elif "未解析到原文链接" in status:
            unresolved_transit += 1
        elif "未进入正文读取候选" in status:
            not_selected += 1
        elif "正文不可用" in status:
            failed_fetch += 1
        else:
            title_only += 1

    without_text = total - with_text

    return {
        "total": total,
        "with_text": with_text,
        "without_text": without_text,
        "title_only": title_only,
        "unresolved_transit": unresolved_transit,
        "not_selected": not_selected,
        "failed_fetch": failed_fetch,
    }


def _collect_warnings(news_items: list[dict], coverage: dict) -> list[str]:
    warnings: list[str] = []
    total = coverage["total"]
    with_text = coverage["with_text"]

    if total == 0:
        return warnings

    if with_text == 0:
        warnings.append(f"0/{total} 条读到正文，所有结果仅能依据标题与来源推断")
        return warnings

    if with_text < total:
        warnings.append(f"只有 {with_text}/{total} 条读到正文，{total - with_text} 条为标题级线索")

    if coverage["unresolved_transit"] > 0:
        warnings.append(f"{coverage['unresolved_transit']} 条 Google News 原文链接未解析")

    if coverage["failed_fetch"] > 0:
        warnings.append(f"{coverage['failed_fetch']} 条正文提取失败，使用标题与来源")

    return warnings


# ── Stage functions used by the server-owned NewsService ────────────────


def run_digest_stage(
    news_items: list[dict],
    query_text: str,
    performance_mode: str,
    selected_model: str,
    progress: ProgressCallback | None = None,
) -> tuple[str, str, dict, list[str]]:
    """Stage 3: generate digest and source block from (enriched) items."""
    if progress:
        progress("正在整理搜索摘要...")

    article_coverage = _compute_article_coverage(news_items)
    warnings = _collect_warnings(news_items, article_coverage)

    digest = generate_news_digest(
        news_items,
        performance_mode=performance_mode,
        selected_model=selected_model,
    )
    source_block = format_news_source_block(query_text, news_items)

    return digest, source_block, article_coverage, warnings


def run_discussion_stage(
    digest: str,
    interaction_mode: str,
    performance_mode: str,
    selected_model: str,
    source_block: str = "",
    session_id: str = "",
    progress: ProgressCallback | None = None,
    persist_group: bool = True,
) -> tuple[str, str]:
    """Stage 4: generate group discussion, write to group file, return (discussion, group_content)."""
    if progress:
        progress("正在生成群聊讨论...")

    discussion = generate_wechat_news_discussion(
        digest,
        relationship_mode=interaction_mode,
        performance_mode=performance_mode,
        selected_model=selected_model,
        session_id=session_id,
    )

    if progress:
        progress("正在写入群聊...")

    group_content = ""
    if persist_group:
        if source_block:
            append_system_group_note(source_block)
        append_interactive_group_reply(discussion)
        update_wechat_join_state(
            user_has_joined=False,
            first_reaction_done=False,
            mode="interactive_group",
        )
        group_content = read_wechat_group()
    return discussion, group_content
