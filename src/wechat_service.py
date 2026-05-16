from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class NewsRoundResult:
    query_text: str
    news_items: list[dict]
    digest: str
    discussion: str
    group_content: str


def run_news_round(
    query_text: str,
    read_articles: bool,
    runtime_context: RuntimeContext,
) -> NewsRoundResult:
    query_text = (query_text or "最新新闻 when:1d").strip()
    progress = runtime_context.progress

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

    append_system_group_note(format_news_source_block(query_text, news_items))
    append_interactive_group_reply(discussion)
    group_content = read_wechat_group()

    if runtime_context.session_id:
        set_wechat_interactive(runtime_context.session_id, "news_round")

    return NewsRoundResult(
        query_text=query_text,
        news_items=news_items,
        digest=digest,
        discussion=discussion,
        group_content=group_content,
    )
