"""News digest generation and source block formatting."""

from __future__ import annotations

import re

from src.llm_client import ModelProfile, chat
from src.news.link_resolver import _display_link_host
from src.performance_budget import news_digest_max_tokens
from src.news.rss_fetcher import normalize_news_query


# ── Title / display helpers ───────────────────────────────────────────


def _display_news_title(title: str, max_chars: int = 28) -> str:
    title = re.sub(r"\s+", " ", (title or "").strip())
    if not title:
        return "未命名条目"
    if len(title) <= max_chars:
        return title
    return title[: max_chars - 3].rstrip() + "..."


# ── News formatting / display helpers ─────────────────────────────────


def _news_article_coverage_summary(news_items: list[dict]) -> str:
    total = len(news_items)
    with_article_text = sum(
        1
        for item in news_items
        if item.get("article_excerpt")
        or str(item.get("article_status", "")).startswith("正文已读")
    )
    without_article_text = total - with_article_text

    if total <= 0:
        return "本轮没有可用搜索结果。"

    if with_article_text == 0:
        return (
            f"本轮共 {total} 条结果，0 条读到页面文本，{without_article_text}"
            " 条仅能依据标题、来源和时间概括。"
            "如果要总结，只能给出保守判断，不要把标题线索写成确定事实。"
        )

    if with_article_text == total:
        return (
            f"本轮共 {total} 条结果，{with_article_text} 条都读到了页面文本，"
            "可优先依据页面文本摘录总结。"
        )

    return (
        f"本轮共 {total} 条结果，其中 {with_article_text} 条读到了页面文本，"
        f"{without_article_text} 条只能依据标题、来源和时间概括。"
        "对没有页面文本的条目，必须明确边界，避免写成确定事实。"
    )


def format_news_source_block(query_text: str, news_items: list[dict]) -> str:
    query_text = normalize_news_query(query_text)
    lines = [f"【联网检索】\n查询：{query_text}"]

    for idx, item in enumerate(news_items[:10], start=1):
        title = _display_news_title(item.get("title", ""))
        source = item.get("source", "新闻源")
        published_at = item.get("published_at", "今天")
        link = item.get("resolved_link") or item.get("link", "")
        article_status = item.get("article_status", "仅标题")
        lines.append(f"{idx}. {title}")
        lines.append(f"   来源：{source}｜{published_at}｜{article_status}")
        if link:
            host = _display_link_host(link) or "打开来源"
            lines.append(f"   链接：{host}")

    return "\n".join(lines).strip()


def _format_news_items_for_digest(news_items: list[dict]) -> str:
    lines: list[str] = []

    for idx, item in enumerate(news_items, start=1):
        title = item.get("title", "")
        source = item.get("source", "新闻源")
        published_at = item.get("published_at", "今天")
        link = item.get("resolved_link") or item.get("link", "")
        link_host = _display_link_host(link) or "未知来源"
        article_status = item.get("article_status", "仅标题")
        article_excerpt = item.get("article_excerpt", "")

        lines.append(f"{idx}. {title}")
        lines.append(f"来源：{source}")
        lines.append(f"时间：{published_at}")
        lines.append(f"链接域名：{link_host}")
        lines.append(f"正文状态：{article_status}")

        if article_excerpt:
            lines.append("页面文本摘录：")
            lines.append(article_excerpt)

        lines.append("")

    return "\n".join(lines).strip()


# ── Model profile resolution (inlined to avoid circular import) ───────


def _resolve_model_profile(
    selected_model: str = "auto",
    performance_mode: str = "standard",
) -> ModelProfile:
    if performance_mode == "deep":
        return "pro"
    if performance_mode == "fast":
        return "flash"
    if selected_model == "pro":
        return "pro"
    return "flash"


# ── Digest generation ─────────────────────────────────────────────────


def generate_news_digest(
    news_items: list[dict],
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    if not news_items:
        return ""

    model_profile = _resolve_model_profile(selected_model, performance_mode)
    coverage_summary = _news_article_coverage_summary(news_items)
    items_text = _format_news_items_for_digest(news_items)
    messages = [
        {
            "role": "system",
            "content": (
                "你要基于联网搜索结果整理一份"
                "简洁、结构化的中文摘要。"
                "部分条目可能包含页面文本摘录"
                "，部分条目可能只有标题、来源"
                "和时间。\n\n"
                "要求：\n"
                "1. 优先依据“页面文本摘录”总结；\n"
                "2. 没有页面文本摘录的条目，"
                "只能基于标题、来源和时间谨慎概括；\n"
                "3. 不要假装读取了没有提供的正文；\n"
                "4. 不要补充搜索结果中没有的信息；\n"
                "5. 如果所有条目都没有正文，"
                "只能给出保守判断；\n"
                "6. 明确指出哪些结论来自页面文本，"
                "哪些只是标题层面的线索。\n\n"
                "输出格式：\n"
                "【搜索结果摘要】\n"
                "1. 主题一\n"
                "- 主要信息\n"
                "- 依据来源：页面文本 / 标题来源\n"
                "- 信息边界\n"
                "2. 主题二\n"
                "- 主要信息\n"
                "- 依据来源：页面文本 / 标题来源\n"
                "- 信息边界\n"
            ),
        },
        {
            "role": "user",
            "content": (
                "下面是 5 到 10 条搜索结果。\n"
                f"正文覆盖情况：{coverage_summary}\n\n"
                f"{items_text}"
            ),
        },
    ]
    return chat(
        messages,
        temperature=0.3,
        model_profile=model_profile,
        max_tokens=news_digest_max_tokens(performance_mode),
        task_name="news_digest",
    ).strip()
