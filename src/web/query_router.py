"""Deterministic query intent routing for web research."""

from __future__ import annotations

import re
from enum import StrEnum

from src.news.url_normalizer import is_public_http_url


class SearchIntent(StrEnum):
    NEWS = "news"
    TECHNICAL = "technical"
    ACADEMIC = "academic"
    SOURCE_CODE = "source_code"
    DIRECT_URL = "direct_url"
    GENERAL = "general"


def route_query(query: str) -> SearchIntent:
    text = re.sub(r"\s+", " ", (query or "").strip())
    lowered = text.lower()
    if is_public_http_url(text):
        return SearchIntent.DIRECT_URL
    if any(token in lowered for token in ("github", "source code", "源码", "issue", "pull request")):
        return SearchIntent.SOURCE_CODE
    if any(token in lowered for token in ("arxiv", "doi", "paper", "论文", "学术", "研究")):
        return SearchIntent.ACADEMIC
    if any(token in lowered for token in ("error", "exception", "traceback", "报错", "文档", "api", "sdk")):
        return SearchIntent.TECHNICAL
    if any(token in lowered for token in ("news", "latest", "today", "新闻", "最新", "今天", "最近")):
        return SearchIntent.NEWS
    return SearchIntent.GENERAL
