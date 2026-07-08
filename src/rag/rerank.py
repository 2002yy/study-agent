from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from src.rag.index import _tokenize
from src.rag.schema import RagSearchResult


@dataclass(frozen=True)
class RerankerConfig:
    name: str = "disabled"
    top_n: int = 20
    latency_budget_ms: int = 250
    cost_budget: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.name not in {"", "disabled", "none", "off"}


@dataclass(frozen=True)
class RerankOutcome:
    results: list[RagSearchResult]
    stage: dict


class Reranker(Protocol):
    name: str

    def rerank(
        self,
        query: str,
        results: list[RagSearchResult],
        *,
        top_n: int,
    ) -> list[RagSearchResult]:
        """Return results in reranked order."""


class DisabledReranker:
    name = "disabled"

    def rerank(
        self,
        query: str,
        results: list[RagSearchResult],
        *,
        top_n: int,
    ) -> list[RagSearchResult]:
        _ = query, top_n
        return results


class LexicalOverlapReranker:
    name = "lexical_overlap"

    def rerank(
        self,
        query: str,
        results: list[RagSearchResult],
        *,
        top_n: int,
    ) -> list[RagSearchResult]:
        query_terms = set(_tokenize(query))
        if not query_terms or top_n <= 0:
            return results

        head = results[:top_n]
        tail = results[top_n:]
        ranked = sorted(
            enumerate(head),
            key=lambda item: (
                -_overlap_score(query_terms, item[1]),
                -item[1].score,
                item[1].chunk.chunk_index,
                item[0],
            ),
        )
        return [result for _index, result in ranked] + tail


def apply_reranker(
    query: str,
    results: list[RagSearchResult],
    *,
    config: RerankerConfig | None = None,
) -> RerankOutcome:
    resolved = config or reranker_config_from_env()
    if not resolved.enabled:
        return RerankOutcome(results=results, stage=_skipped_stage(resolved, len(results)))

    reranker = get_reranker(resolved.name)
    candidate_count = min(len(results), resolved.top_n)
    started = time.perf_counter()
    reranked = reranker.rerank(query, results, top_n=resolved.top_n)
    elapsed_ms = (time.perf_counter() - started) * 1000
    estimated_cost = _estimated_cost(resolved.name, candidate_count)
    return RerankOutcome(
        results=reranked,
        stage={
            "name": f"reranker:{reranker.name}",
            "candidate_count": len(results),
            "reranked_count": candidate_count,
            "elapsed_ms": round(elapsed_ms, 3),
            "latency_budget_ms": resolved.latency_budget_ms,
            "within_latency_budget": elapsed_ms <= resolved.latency_budget_ms,
            "estimated_cost": estimated_cost,
            "cost_budget": resolved.cost_budget,
            "within_cost_budget": estimated_cost <= resolved.cost_budget,
        },
    )


def get_reranker(name: str = "disabled") -> Reranker:
    normalized = (name or "disabled").strip().lower()
    if normalized in {"", "disabled", "none", "off"}:
        return DisabledReranker()
    if normalized in {"lexical", "lexical_overlap", "overlap"}:
        return LexicalOverlapReranker()
    raise ValueError(f"Unsupported RAG reranker: {name}")


def reranker_config_from_env(
    *,
    name: str | None = None,
    top_n: int | None = None,
    latency_budget_ms: int | None = None,
    cost_budget: float | None = None,
) -> RerankerConfig:
    resolved_name = name if name is not None else os.getenv("RAG_RERANKER", "disabled")
    return RerankerConfig(
        name=(resolved_name or "disabled").strip().lower() or "disabled",
        top_n=top_n if top_n is not None else _env_int("RAG_RERANK_TOP_N", 20),
        latency_budget_ms=latency_budget_ms
        if latency_budget_ms is not None
        else _env_int("RAG_RERANK_LATENCY_BUDGET_MS", 250),
        cost_budget=cost_budget
        if cost_budget is not None
        else _env_float("RAG_RERANK_COST_BUDGET", 0.0),
    )


def _overlap_score(query_terms: set[str], result: RagSearchResult) -> float:
    result_terms = set(result.matched_terms) or set(_tokenize(result.chunk.text))
    if not result_terms:
        return 0.0
    return len(query_terms & result_terms) / len(query_terms)


def _skipped_stage(config: RerankerConfig, candidate_count: int) -> dict:
    return {
        "name": "reranker:disabled",
        "candidate_count": candidate_count,
        "reranked_count": 0,
        "elapsed_ms": 0.0,
        "latency_budget_ms": config.latency_budget_ms,
        "within_latency_budget": True,
        "estimated_cost": 0.0,
        "cost_budget": config.cost_budget,
        "within_cost_budget": True,
        "skipped": True,
    }


def _estimated_cost(name: str, candidate_count: int) -> float:
    _ = name, candidate_count
    return 0.0


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed
