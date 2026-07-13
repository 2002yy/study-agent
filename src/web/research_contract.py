"""Deterministic research context and bounded query planning.

This module is the first G10 slice. It contains no provider or persistence logic;
it turns a user query into a stable, date-aware contract that both direct lookup
and the future durable research state machine can consume.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from src.web.query_normalizer import normalize_web_query


@dataclass(frozen=True)
class ResearchContext:
    raw_query: str
    canonical_query: str
    query_variants: tuple[str, ...]
    as_of_date: str
    freshness_days: int | None
    freshness_requested: bool
    entity_aliases: tuple[str, ...] = ()
    search_directive_removed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueryAttempt:
    query: str
    status: str
    result_count: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_research_context(
    query: str,
    *,
    now: datetime | None = None,
    max_query_variants: int = 3,
) -> ResearchContext:
    """Build a bounded, deterministic research context.

    The raw spelling is always retained. The query list is bounded here so a
    direct lookup cannot accidentally expand into an unbounded research loop.
    A later ResearchRun planner may request additional variants explicitly.
    """

    normalized = normalize_web_query(query, now=now)
    limit = max(1, min(int(max_query_variants), 8))
    variants = tuple(normalized.query_variants[:limit])
    return ResearchContext(
        raw_query=normalized.raw_query,
        canonical_query=normalized.canonical_query,
        query_variants=variants,
        as_of_date=normalized.as_of_date,
        freshness_days=normalized.freshness_days,
        freshness_requested=normalized.freshness_requested,
        entity_aliases=normalized.entity_aliases,
        search_directive_removed=normalized.search_directive_removed,
    )


def successful_attempt(query: str, result_count: int) -> QueryAttempt:
    count = max(0, int(result_count))
    return QueryAttempt(
        query=query,
        status="found" if count else "empty",
        result_count=count,
    )


def failed_attempt(query: str, error: Exception | str) -> QueryAttempt:
    return QueryAttempt(query=query, status="provider_failed", error=str(error))


def stop_reason(attempts: list[QueryAttempt]) -> str:
    """Return an evidence-safe stop reason for a bounded direct lookup."""

    if any(attempt.status == "found" for attempt in attempts):
        return "direct_results_found"
    if attempts and all(attempt.status == "provider_failed" for attempt in attempts):
        return "providers_failed"
    return "providers_returned_no_results"
