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
    query_text = (query_text or "最新新闻 when:1d").strip()
    progress = runtime_context.progress

    warnings: list[str] = []

    if progress:
        progress(f"正在搜索：{query_text}")

    news_items = fetch_news_items(query_text=query_text, max_items=10)
    if len(news_items) < 3:
        raise RuntimeError("搜索结果数量不足，暂时没法组织一轮像样的群聊讨论。")

    if read_articles:
        if progress:
            progress("正在尝试读取新闻正文...")
        news_items = enrich_news_items_with_article_text(
            news_items,
            max_articles=5,
            max_chars_per_article=5000,
            query_text=query_text,
        )

    article_coverage = _compute_article_coverage(news_items)
    warnings.extend(_collect_warnings(news_items, article_coverage))

    if progress:
        progress("正在整理搜索摘要...")

    digest = generate_news_digest(
        news_items,
        performance_mode=runtime_context.performance_mode,
        selected_model=runtime_context.selected_model,
    )

    if progress:
        progress("正在生成群聊讨论...")

    discussion = generate_wechat_news_discussion(
        digest,
        relationship_mode=runtime_context.interaction_mode,
        performance_mode=runtime_context.performance_mode,
        selected_model=runtime_context.selected_model,
    )

    if progress:
        progress("正在写入群聊...")

    source_block = format_news_source_block(query_text, news_items)
    append_system_group_note(source_block)
    append_interactive_group_reply(discussion)
    group_content = read_wechat_group()

    if runtime_context.session_id:
        set_wechat_interactive(runtime_context.session_id, "news_round")

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
