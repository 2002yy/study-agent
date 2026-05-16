from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from src.session_logger import set_wechat_interactive
from src.wechat import (
    append_interactive_group_reply,
    append_system_group_note,
    enrich_news_items_with_article_text,
    fetch_news_items,
    format_news_source_block,
    generate_news_digest,
    generate_wechat_news_discussion,
    read_wechat_group,
)


ProgressCallback = Callable[[str], None]


def max_articles_for_performance(performance_mode: str) -> int:
    """Map performance_mode to article count for body text enrichment."""
    return {"fast": 2, "standard": 4, "deep": 6}.get(performance_mode, 4)


@dataclass(frozen=True)
class RuntimeContext:
    performance_mode: str
    selected_model: str
    interaction_mode: str
    session_id: str = ""
    progress: ProgressCallback | None = None


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


# ── Stage functions for phased news round ──────────────────────────────


def run_search_stage(
    query_text: str,
    max_items: int = 10,
    progress: ProgressCallback | None = None,
) -> list[dict]:
    """Stage 1: fetch & dedupe news items (no article text)."""
    query_text = (query_text or "最新新闻 when:1d").strip()
    if progress:
        progress(f"正在搜索：{query_text}")
    news_items = fetch_news_items(query_text=query_text, max_items=max_items)
    if len(news_items) < 3:
        raise RuntimeError("搜索结果数量不足，暂时没法组织一轮像样的群聊讨论。")
    return news_items


def run_enrich_stage(
    news_items: list[dict],
    max_articles: int,
    query_text: str = "",
    max_chars_per_article: int = 5000,
    progress: ProgressCallback | None = None,
) -> list[dict]:
    """Stage 2: fetch article body text for top-ranked items."""
    if progress:
        progress("正在尝试读取新闻正文...")
    return enrich_news_items_with_article_text(
        news_items,
        max_articles=max_articles,
        max_chars_per_article=max_chars_per_article,
        query_text=query_text,
    )


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
) -> tuple[str, str]:
    """Stage 4: generate group discussion, write to group file, return (discussion, group_content)."""
    if progress:
        progress("正在生成群聊讨论...")

    discussion = generate_wechat_news_discussion(
        digest,
        relationship_mode=interaction_mode,
        performance_mode=performance_mode,
        selected_model=selected_model,
    )

    if progress:
        progress("正在写入群聊...")

    if source_block:
        append_system_group_note(source_block)
    append_interactive_group_reply(discussion)
    group_content = read_wechat_group()

    if session_id:
        set_wechat_interactive(session_id, "news_round")

    return discussion, group_content


# ── Legacy monolithic runner (delegates to stage functions) ────────────


@dataclass(frozen=True)
class NewsRoundResult:
    query_text: str
    news_items: list[dict]
    digest: str
    discussion: str
    group_content: str
    source_block: str = ""
    article_coverage: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    warnings: list[str] = field(default_factory=list)


def run_news_round(
    query_text: str,
    read_articles: bool,
    runtime_context: RuntimeContext,
) -> NewsRoundResult:
    t0 = time.perf_counter()
    progress = runtime_context.progress

    news_items = run_search_stage(query_text, progress=progress)

    if read_articles:
        max_articles = max_articles_for_performance(runtime_context.performance_mode)
        news_items = run_enrich_stage(
            news_items,
            max_articles=max_articles,
            query_text=query_text,
            progress=progress,
        )

    digest, source_block, article_coverage, warnings = run_digest_stage(
        news_items,
        query_text=query_text,
        performance_mode=runtime_context.performance_mode,
        selected_model=runtime_context.selected_model,
        progress=progress,
    )

    discussion, group_content = run_discussion_stage(
        digest,
        interaction_mode=runtime_context.interaction_mode,
        performance_mode=runtime_context.performance_mode,
        selected_model=runtime_context.selected_model,
        source_block=source_block,
        session_id=runtime_context.session_id,
        progress=progress,
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    return NewsRoundResult(
        query_text=query_text,
        news_items=news_items,
        digest=digest,
        discussion=discussion,
        group_content=group_content,
        source_block=source_block,
        article_coverage=article_coverage,
        elapsed_ms=elapsed_ms,
        warnings=warnings,
    )
