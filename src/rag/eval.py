from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rag.schema import RagIndex, RagSearchResult
from src.rag.service import search_documents


@dataclass(frozen=True)
class RagEvalCase:
    query: str
    expected_sources: tuple[str, ...]
    expected_terms: tuple[str, ...] = ()
    top_k: int = 3
    retrieval_mode: str = "hybrid"
    reranker: str = "disabled"


@dataclass(frozen=True)
class RagEvalProfile:
    name: str
    retrieval_mode: str
    reranker: str = "disabled"


@dataclass(frozen=True)
class RagEvalResult:
    case: RagEvalCase
    result_count: int
    retrieved_sources: tuple[str, ...]
    first_relevant_rank: int | None
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    matched_expected_terms: tuple[str, ...]

    @property
    def hit(self) -> bool:
        return self.first_relevant_rank is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.case.query,
            "retrieval_mode": self.case.retrieval_mode,
            "top_k": self.case.top_k,
            "expected_sources": list(self.case.expected_sources),
            "retrieved_sources": list(self.retrieved_sources),
            "result_count": self.result_count,
            "hit": self.hit,
            "first_relevant_rank": self.first_relevant_rank,
            "recall_at_k": self.recall_at_k,
            "reciprocal_rank": self.reciprocal_rank,
            "ndcg_at_k": self.ndcg_at_k,
            "matched_expected_terms": list(self.matched_expected_terms),
        }


@dataclass(frozen=True)
class RagEvalSummary:
    total_cases: int
    source_hit_rate: float
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    mean_ndcg_at_k: float
    empty_result_rate: float
    results: tuple[RagEvalResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "source_hit_rate": self.source_hit_rate,
            "mean_recall_at_k": self.mean_recall_at_k,
            "mean_reciprocal_rank": self.mean_reciprocal_rank,
            "mean_ndcg_at_k": self.mean_ndcg_at_k,
            "empty_result_rate": self.empty_result_rate,
            "results": [result.to_dict() for result in self.results],
        }


def _search(
    index: RagIndex,
    case: RagEvalCase,
    *,
    min_score: float,
) -> list[RagSearchResult]:
    return search_documents(
        index,
        case.query,
        top_k=case.top_k,
        min_score=min_score,
        retrieval_mode=case.retrieval_mode,
        reranker=case.reranker,
    )


def _source_matches(actual: str, expected: str) -> bool:
    actual_path = Path(actual)
    expected_path = Path(expected)
    actual_norm = actual.replace("\\", "/")
    expected_norm = expected.replace("\\", "/")
    return (
        actual_norm == expected_norm
        or actual_norm.endswith("/" + expected_norm)
        or actual_path.name == expected_path.name
    )


def _matches_expected_source(source: str, expected_sources: tuple[str, ...]) -> bool:
    return any(_source_matches(source, expected) for expected in expected_sources)


def _matched_expected_terms(
    results: list[RagSearchResult],
    expected_terms: tuple[str, ...],
) -> tuple[str, ...]:
    matched_terms = {term.lower() for result in results for term in result.matched_terms}
    matched_text = "\n".join(result.chunk.text.lower() for result in results)
    found = [
        term
        for term in expected_terms
        if term.lower() in matched_terms or term.lower() in matched_text
    ]
    return tuple(found)


def load_eval_cases(path: str | Path) -> tuple[RagEvalCase, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases", data)
    if not isinstance(cases, list):
        raise ValueError("RAG eval cases must be a list or contain a 'cases' list")

    loaded: list[RagEvalCase] = []
    for item in cases:
        expected_sources = tuple(str(source) for source in item.get("expected_sources", ()))
        if not expected_sources:
            raise ValueError("RAG eval case requires expected_sources")
        loaded.append(
            RagEvalCase(
                query=str(item["query"]),
                expected_sources=expected_sources,
                expected_terms=tuple(str(term) for term in item.get("expected_terms", ())),
                top_k=int(item.get("top_k", 3)),
                retrieval_mode=str(item.get("retrieval_mode", "hybrid")),
                reranker=str(item.get("reranker", "disabled")),
            )
        )
    return tuple(loaded)


def default_eval_profiles() -> tuple[RagEvalProfile, ...]:
    return (
        RagEvalProfile(name="lexical", retrieval_mode="lexical"),
        RagEvalProfile(name="vector", retrieval_mode="vector"),
        RagEvalProfile(name="hybrid", retrieval_mode="hybrid"),
        RagEvalProfile(
            name="hybrid_reranked",
            retrieval_mode="hybrid",
            reranker="lexical_overlap",
        ),
    )


def evaluate_case(
    index: RagIndex,
    case: RagEvalCase,
    *,
    min_score: float = 0.01,
) -> RagEvalResult:
    results = _search(index, case, min_score=min_score)
    retrieved_sources = tuple(result.chunk.source_path for result in results)
    matching_ranks = [
        rank
        for rank, source in enumerate(retrieved_sources, start=1)
        if _matches_expected_source(source, case.expected_sources)
    ]
    matched_expected = {
        expected
        for expected in case.expected_sources
        if any(_source_matches(source, expected) for source in retrieved_sources)
    }
    recall = len(matched_expected) / len(case.expected_sources)
    first_rank = min(matching_ranks) if matching_ranks else None
    reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
    ndcg = _ndcg_at_k(retrieved_sources, case.expected_sources, case.top_k)

    return RagEvalResult(
        case=case,
        result_count=len(results),
        retrieved_sources=retrieved_sources,
        first_relevant_rank=first_rank,
        recall_at_k=round(recall, 6),
        reciprocal_rank=round(reciprocal_rank, 6),
        ndcg_at_k=round(ndcg, 6),
        matched_expected_terms=_matched_expected_terms(results, case.expected_terms),
    )


def evaluate_rag_index(
    index: RagIndex,
    cases: tuple[RagEvalCase, ...],
    *,
    min_score: float = 0.01,
) -> RagEvalSummary:
    results = tuple(evaluate_case(index, case, min_score=min_score) for case in cases)
    total = len(results)
    if total == 0:
        return RagEvalSummary(
            total_cases=0,
            source_hit_rate=0.0,
            mean_recall_at_k=0.0,
            mean_reciprocal_rank=0.0,
            mean_ndcg_at_k=0.0,
            empty_result_rate=0.0,
            results=(),
        )

    return RagEvalSummary(
        total_cases=total,
        source_hit_rate=round(sum(1 for result in results if result.hit) / total, 6),
        mean_recall_at_k=round(sum(result.recall_at_k for result in results) / total, 6),
        mean_reciprocal_rank=round(
            sum(result.reciprocal_rank for result in results) / total,
            6,
        ),
        mean_ndcg_at_k=round(sum(result.ndcg_at_k for result in results) / total, 6),
        empty_result_rate=round(sum(1 for result in results if result.result_count == 0) / total, 6),
        results=results,
    )


def evaluate_retrieval_profiles(
    index: RagIndex,
    cases: tuple[RagEvalCase, ...],
    *,
    profiles: tuple[RagEvalProfile, ...] | None = None,
    min_score: float = 0.01,
) -> dict[str, RagEvalSummary]:
    resolved_profiles = profiles or default_eval_profiles()
    return {
        profile.name: evaluate_rag_index(
            index,
            tuple(
                RagEvalCase(
                    query=case.query,
                    expected_sources=case.expected_sources,
                    expected_terms=case.expected_terms,
                    top_k=case.top_k,
                    retrieval_mode=profile.retrieval_mode,
                    reranker=profile.reranker,
                )
                for case in cases
            ),
            min_score=min_score,
        )
        for profile in resolved_profiles
    }


def _ndcg_at_k(
    retrieved_sources: tuple[str, ...],
    expected_sources: tuple[str, ...],
    top_k: int,
) -> float:
    if not expected_sources or top_k <= 0:
        return 0.0
    gains = [
        1.0 if _matches_expected_source(source, expected_sources) else 0.0
        for source in retrieved_sources[:top_k]
    ]
    dcg = _discounted_cumulative_gain(gains)
    ideal_relevant = min(len(expected_sources), top_k)
    ideal_dcg = _discounted_cumulative_gain([1.0] * ideal_relevant)
    return dcg / ideal_dcg if ideal_dcg else 0.0


def _discounted_cumulative_gain(gains: list[float]) -> float:
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
