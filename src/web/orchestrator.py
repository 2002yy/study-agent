"""Small compatibility plan for the current NewsRun-backed web workflow."""

from __future__ import annotations

from dataclasses import dataclass

from src.web.query_router import SearchIntent, route_query


@dataclass(frozen=True)
class WebSearchPlan:
    query: str
    intent: SearchIntent
    searxng_categories: str
    include_news_feeds: bool
    direct_url: str = ""


def build_search_plan(query: str) -> WebSearchPlan:
    normalized = (query or "").strip()
    intent = route_query(normalized)
    return WebSearchPlan(
        query=normalized,
        intent=intent,
        searxng_categories="news" if intent == SearchIntent.NEWS else "general",
        include_news_feeds=intent == SearchIntent.NEWS,
        direct_url=normalized if intent == SearchIntent.DIRECT_URL else "",
    )
