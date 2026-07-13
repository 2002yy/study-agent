"""Small compatibility plan for the current NewsRun-backed web workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.web.query_normalizer import normalize_web_query
from src.web.query_router import SearchIntent, route_query


@dataclass(frozen=True)
class WebSearchPlan:
    query: str
    canonical_query: str
    query_variants: tuple[str, ...]
    intent: SearchIntent
    searxng_categories: str
    include_news_feeds: bool
    as_of_date: str
    freshness_days: int | None
    entity_aliases: tuple[str, ...] = ()
    direct_url: str = ""


def build_search_plan(query: str, *, now: datetime | None = None) -> WebSearchPlan:
    normalized = normalize_web_query(query, now=now)
    intent = route_query(normalized.canonical_query)
    return WebSearchPlan(
        query=normalized.raw_query,
        canonical_query=normalized.canonical_query,
        query_variants=normalized.query_variants,
        intent=intent,
        searxng_categories="news" if intent == SearchIntent.NEWS else "general",
        include_news_feeds=intent == SearchIntent.NEWS,
        as_of_date=normalized.as_of_date,
        freshness_days=normalized.freshness_days,
        entity_aliases=normalized.entity_aliases,
        direct_url=(
            normalized.raw_query if intent == SearchIntent.DIRECT_URL else ""
        ),
    )
