"""Query-batch execution and provenance-preserving CandidatePool merge.

The executor intentionally runs every planned query. A non-empty result from an
earlier query never closes the batch. This module performs URL safety,
canonicalization and deduplication only; relevance, role-fit, semantic rerank,
source clustering and read scheduling belong to later RQCE-P1 slices.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any

from src.news.url_normalizer import canonicalize_url
from src.web.research.gap_planner import GapQueryBatch, GapSearchIntent, PlannedGapQuery
from src.web.research.selection_trace import SelectionTraceCollector

DEFAULT_RESULTS_PER_QUERY = 5
DEFAULT_MAX_POOL_CANDIDATES = 20

SearchExact = Callable[..., Mapping[str, Any]]
CancellationCheck = Callable[[], bool]
Checkpoint = Callable[["CandidatePoolProgress"], None]


class CandidatePoolCancelled(RuntimeError):
    """Raised at a cooperative checkpoint when the owning run is cancelled."""


@dataclass(frozen=True)
class QuerySearchOutcome:
    query_id: str
    intent: GapSearchIntent
    query: str
    status: str
    reason: str
    result_count: int
    providers_attempted: tuple[str, ...] = ()
    provider_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "intent": self.intent.value,
            "query": self.query,
            "status": self.status,
            "reason": self.reason,
            "result_count": self.result_count,
            "providers_attempted": list(self.providers_attempted),
            "provider_errors": list(self.provider_errors),
        }


@dataclass(frozen=True)
class CandidatePoolItem:
    id: str
    canonical_url: str
    url: str
    title: str
    snippet: str
    source: str
    published_at: str
    query_ids: tuple[str, ...]
    intents: tuple[GapSearchIntent, ...]
    providers: tuple[str, ...]
    first_seen_rank: int
    # Slice 2 provenance (discovery only; identity stays the canonical URL).
    parent_lead_candidate_id: str = ""
    discovery_method: str = ""
    discovery_depth: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_url": self.canonical_url,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source": self.source,
            "published_at": self.published_at,
            "query_ids": list(self.query_ids),
            "intents": [intent.value for intent in self.intents],
            "providers": list(self.providers),
            "first_seen_rank": self.first_seen_rank,
            "parent_lead_candidate_id": self.parent_lead_candidate_id,
            "discovery_method": self.discovery_method,
            "discovery_depth": self.discovery_depth,
        }


@dataclass(frozen=True)
class CandidatePoolProgress:
    gap_id: str
    completed_queries: int
    total_queries: int
    latest_outcome: QuerySearchOutcome
    candidate_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "completed_queries": self.completed_queries,
            "total_queries": self.total_queries,
            "latest_outcome": self.latest_outcome.to_dict(),
            "candidate_count": self.candidate_count,
        }


@dataclass(frozen=True)
class CandidatePoolBatchResult:
    gap_id: str
    claim_id: str
    outcomes: tuple[QuerySearchOutcome, ...]
    candidates: tuple[CandidatePoolItem, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "claim_id": self.claim_id,
            "outcomes": [item.to_dict() for item in self.outcomes],
            "candidates": [item.to_dict() for item in self.candidates],
            "status": self.status,
        }


def execute_candidate_pool_batch(
    batch: GapQueryBatch,
    *,
    search_exact: SearchExact,
    should_cancel: CancellationCheck | None = None,
    checkpoint: Checkpoint | None = None,
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY,
    max_candidates: int = DEFAULT_MAX_POOL_CANDIDATES,
    trace: SelectionTraceCollector | None = None,
) -> CandidatePoolBatchResult:
    """Execute all planned queries and merge their result provenance."""

    if not batch.queries:
        raise ValueError("candidate pool batch requires planned queries")
    per_query_limit = max(1, min(int(results_per_query), 12))
    pool_limit = max(1, min(int(max_candidates), 100))
    outcomes: list[QuerySearchOutcome] = []
    candidates: tuple[CandidatePoolItem, ...] = ()
    raw_batches: list[tuple[PlannedGapQuery, tuple[Mapping[str, Any], ...], tuple[str, ...]]] = []

    for planned in batch.queries:
        _ensure_active(should_cancel)
        try:
            payload = search_exact(planned.query, max_results=per_query_limit)
            if not isinstance(payload, Mapping):
                raise ValueError("search_exact must return a mapping")
            raw_results = tuple(
                item
                for item in payload.get("results", [])
                if isinstance(item, Mapping)
            )
            if trace is not None:
                for raw in raw_results:
                    trace.note_seen(raw.get("url") or raw.get("link"))
            providers = _strings(payload.get("providers_attempted", []), limit=12)
            provider_errors = _strings(payload.get("provider_errors", []), limit=24)
            status = _bounded_text(payload.get("status"), 100) or (
                "ok" if raw_results else "empty"
            )
            reason = _bounded_text(payload.get("reason"), 200)
        except Exception as exc:
            raw_results = ()
            providers = ()
            provider_errors = (f"search_exception:{type(exc).__name__}",)
            status = "unavailable"
            reason = "search_exception"
        outcome = QuerySearchOutcome(
            query_id=planned.id,
            intent=planned.intent,
            query=planned.query,
            status=status,
            reason=reason,
            result_count=len(raw_results),
            providers_attempted=providers,
            provider_errors=provider_errors,
        )
        outcomes.append(outcome)
        raw_batches.append((planned, raw_results, providers))
        candidates = merge_candidate_pool(
            raw_batches, max_candidates=pool_limit, trace=trace
        )
        _ensure_active(should_cancel)
        if checkpoint is not None:
            checkpoint(
                CandidatePoolProgress(
                    gap_id=batch.gap_id,
                    completed_queries=len(outcomes),
                    total_queries=len(batch.queries),
                    latest_outcome=outcome,
                    candidate_count=len(candidates),
                )
            )

    status = "completed" if candidates else (
        "unavailable"
        if outcomes and all(item.status == "unavailable" for item in outcomes)
        else "empty"
    )
    return CandidatePoolBatchResult(
        gap_id=batch.gap_id,
        claim_id=batch.claim_id,
        outcomes=tuple(outcomes),
        candidates=candidates,
        status=status,
    )


def merge_candidate_pool(
    batches: list[
        tuple[PlannedGapQuery, tuple[Mapping[str, Any], ...], tuple[str, ...]]
    ],
    *,
    max_candidates: int = DEFAULT_MAX_POOL_CANDIDATES,
    trace: SelectionTraceCollector | None = None,
) -> tuple[CandidatePoolItem, ...]:
    """Canonicalize and dedupe results while retaining all discovery paths."""

    limit = max(1, min(int(max_candidates), 100))
    ordered: list[CandidatePoolItem] = []
    positions: dict[str, int] = {}
    seen_rank = 0
    for planned, results, payload_providers in batches:
        for raw in results:
            canonical = canonicalize_url(
                str(raw.get("url") or raw.get("link") or "")
            )
            title = _bounded_text(raw.get("title") or raw.get("name"), 500)
            if not canonical or not title:
                if trace is not None:
                    trace.note_unusable(
                        raw.get("url") or raw.get("link"),
                        had_canonical=bool(canonical),
                    )
                continue
            if trace is not None:
                trace.note_normalized(canonical)
            source = _bounded_text(raw.get("source"), 200)
            providers = _candidate_providers(raw, payload_providers)
            existing_position = positions.get(canonical)
            if existing_position is not None:
                if trace is not None:
                    trace.note_duplicate(canonical)
                existing = ordered[existing_position]
                ordered[existing_position] = replace(
                    existing,
                    title=_prefer_richer(existing.title, title),
                    snippet=_prefer_richer(
                        existing.snippet,
                        _bounded_text(
                            raw.get("snippet") or raw.get("search_excerpt"),
                            2000,
                        ),
                    ),
                    query_ids=tuple(dict.fromkeys((*existing.query_ids, planned.id))),
                    intents=tuple(dict.fromkeys((*existing.intents, planned.intent))),
                    providers=tuple(dict.fromkeys((*existing.providers, *providers))),
                )
                continue
            if len(ordered) >= limit:
                if trace is not None:
                    trace.note_cap_excluded(canonical, stage="merge_candidate_pool")
                continue
            seen_rank += 1
            item = CandidatePoolItem(
                id=f"candidate_{sha256(canonical.encode('utf-8')).hexdigest()[:16]}",
                canonical_url=canonical,
                url=canonical,
                title=title,
                snippet=_bounded_text(
                    raw.get("snippet") or raw.get("search_excerpt"), 2000
                ),
                source=source,
                published_at=_bounded_text(raw.get("published_at"), 100),
                query_ids=(planned.id,),
                intents=(planned.intent,),
                providers=providers,
                first_seen_rank=seen_rank,
            )
            positions[canonical] = len(ordered)
            ordered.append(item)
            if trace is not None:
                trace.note_materialized(canonical)
    return tuple(ordered)


def _ensure_active(check: CancellationCheck | None) -> None:
    if check is not None and check():
        raise CandidatePoolCancelled("candidate pool batch cancelled")


def _candidate_providers(
    raw: Mapping[str, Any], payload_providers: tuple[str, ...]
) -> tuple[str, ...]:
    """Prefer exact result provenance, falling back only for legacy payloads."""

    listed = _strings(raw.get("providers", []), limit=12)
    singleton = _bounded_text(raw.get("provider"), 100)
    precise = tuple(dict.fromkeys((*listed, singleton))) if singleton else listed
    return precise or payload_providers


def _strings(value: Any, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        dict.fromkeys(
            text
            for item in value[:limit]
            if (text := _bounded_text(item, 300))
        )
    )


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _prefer_richer(current: str, candidate: str) -> str:
    return candidate if len(candidate) > len(current) else current


__all__ = [
    "CandidatePoolBatchResult",
    "CandidatePoolCancelled",
    "CandidatePoolItem",
    "CandidatePoolProgress",
    "DEFAULT_MAX_POOL_CANDIDATES",
    "DEFAULT_RESULTS_PER_QUERY",
    "QuerySearchOutcome",
    "execute_candidate_pool_batch",
    "merge_candidate_pool",
]
