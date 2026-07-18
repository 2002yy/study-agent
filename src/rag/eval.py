from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
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
    case_id: str = ""
    scenario: str = "clean"
    answerable: bool = True
    forbidden_sources: tuple[str, ...] = ()
    metadata_filters: dict[str, Any] = field(default_factory=dict)
    max_chunks_per_source: int = 0
    suppress_duplicate_text: bool = True


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
    precision_at_k: float
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    matched_expected_terms: tuple[str, ...]
    retrieved_forbidden_sources: tuple[str, ...]

    @property
    def hit(self) -> bool:
        return self.first_relevant_rank is not None

    @property
    def forbidden_source_leakage(self) -> bool:
        return bool(self.retrieved_forbidden_sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "scenario": self.case.scenario,
            "query": self.case.query,
            "answerable": self.case.answerable,
            "retrieval_mode": self.case.retrieval_mode,
            "top_k": self.case.top_k,
            "expected_sources": list(self.case.expected_sources),
            "forbidden_sources": list(self.case.forbidden_sources),
            "retrieved_sources": list(self.retrieved_sources),
            "retrieved_forbidden_sources": list(self.retrieved_forbidden_sources),
            "result_count": self.result_count,
            "hit": self.hit,
            "first_relevant_rank": self.first_relevant_rank,
            "precision_at_k": self.precision_at_k,
            "recall_at_k": self.recall_at_k,
            "reciprocal_rank": self.reciprocal_rank,
            "ndcg_at_k": self.ndcg_at_k,
            "matched_expected_terms": list(self.matched_expected_terms),
            "forbidden_source_leakage": self.forbidden_source_leakage,
        }


@dataclass(frozen=True)
class RagEvalSummary:
    total_cases: int
    answerable_cases: int
    unanswerable_cases: int
    source_hit_rate: float
    mean_precision_at_k: float
    mean_recall_at_k: float
    mean_reciprocal_rank: float
    mean_ndcg_at_k: float
    empty_result_rate: float
    unanswerable_nonempty_rate: float
    forbidden_source_leakage_rate: float
    scenario_summaries: dict[str, dict[str, float | int]]
    results: tuple[RagEvalResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "answerable_cases": self.answerable_cases,
            "unanswerable_cases": self.unanswerable_cases,
            "source_hit_rate": self.source_hit_rate,
            "mean_precision_at_k": self.mean_precision_at_k,
            "mean_recall_at_k": self.mean_recall_at_k,
            "mean_reciprocal_rank": self.mean_reciprocal_rank,
            "mean_ndcg_at_k": self.mean_ndcg_at_k,
            "empty_result_rate": self.empty_result_rate,
            "unanswerable_nonempty_rate": self.unanswerable_nonempty_rate,
            "forbidden_source_leakage_rate": self.forbidden_source_leakage_rate,
            "scenario_summaries": self.scenario_summaries,
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
        metadata_filters=case.metadata_filters or None,
        max_chunks_per_source=case.max_chunks_per_source,
        suppress_duplicate_text=case.suppress_duplicate_text,
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
    for index, item in enumerate(cases, start=1):
        answerable = bool(item.get("answerable", True))
        expected_sources = tuple(str(source) for source in item.get("expected_sources", ()))
        if answerable and not expected_sources:
            raise ValueError("Answerable RAG eval case requires expected_sources")
        loaded.append(
            RagEvalCase(
                query=str(item["query"]),
                expected_sources=expected_sources,
                expected_terms=tuple(str(term) for term in item.get("expected_terms", ())),
                top_k=int(item.get("top_k", 3)),
                retrieval_mode=str(item.get("retrieval_mode", "hybrid")),
                reranker=str(item.get("reranker", "disabled")),
                case_id=str(item.get("id", f"case_{index:03d}")),
                scenario=str(item.get("scenario", "clean")),
                answerable=answerable,
                forbidden_sources=tuple(
                    str(source) for source in item.get("forbidden_sources", ())
                ),
                metadata_filters=dict(item.get("metadata_filters", {})),
                max_chunks_per_source=int(item.get("max_chunks_per_source", 0)),
                suppress_duplicate_text=bool(item.get("suppress_duplicate_text", True)),
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
    unique_retrieved = _unique_sources(retrieved_sources)
    matched_expected = {
        expected
        for expected in case.expected_sources
        if any(_source_matches(source, expected) for source in unique_retrieved)
    }
    matched_retrieved = {
        source
        for source in unique_retrieved
        if _matches_expected_source(source, case.expected_sources)
    }
    forbidden_retrieved = tuple(
        source
        for source in unique_retrieved
        if _matches_expected_source(source, case.forbidden_sources)
    )
    precision = (
        len(matched_retrieved) / len(unique_retrieved)
        if unique_retrieved and case.expected_sources
        else 0.0
    )
    recall = (
        len(matched_expected) / len(case.expected_sources)
        if case.expected_sources
        else 0.0
    )
    first_rank = min(matching_ranks) if matching_ranks else None
    reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
    ndcg = _ndcg_at_k(retrieved_sources, case.expected_sources, case.top_k)

    return RagEvalResult(
        case=case,
        result_count=len(results),
        retrieved_sources=retrieved_sources,
        first_relevant_rank=first_rank,
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        reciprocal_rank=round(reciprocal_rank, 6),
        ndcg_at_k=round(ndcg, 6),
        matched_expected_terms=_matched_expected_terms(results, case.expected_terms),
        retrieved_forbidden_sources=forbidden_retrieved,
    )


def evaluate_rag_index(
    index: RagIndex,
    cases: tuple[RagEvalCase, ...],
    *,
    min_score: float = 0.01,
) -> RagEvalSummary:
    results = tuple(evaluate_case(index, case, min_score=min_score) for case in cases)
    return _summarize_results(results)


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
                    case_id=case.case_id,
                    scenario=case.scenario,
                    answerable=case.answerable,
                    forbidden_sources=case.forbidden_sources,
                    metadata_filters=case.metadata_filters,
                    max_chunks_per_source=case.max_chunks_per_source,
                    suppress_duplicate_text=case.suppress_duplicate_text,
                )
                for case in cases
            ),
            min_score=min_score,
        )
        for profile in resolved_profiles
    }


def _summarize_results(results: tuple[RagEvalResult, ...]) -> RagEvalSummary:
    total = len(results)
    answerable_results = tuple(result for result in results if result.case.answerable)
    unanswerable_results = tuple(result for result in results if not result.case.answerable)
    if total == 0:
        return RagEvalSummary(
            total_cases=0,
            answerable_cases=0,
            unanswerable_cases=0,
            source_hit_rate=0.0,
            mean_precision_at_k=0.0,
            mean_recall_at_k=0.0,
            mean_reciprocal_rank=0.0,
            mean_ndcg_at_k=0.0,
            empty_result_rate=0.0,
            unanswerable_nonempty_rate=0.0,
            forbidden_source_leakage_rate=0.0,
            scenario_summaries={},
            results=(),
        )
    return RagEvalSummary(
        total_cases=total,
        answerable_cases=len(answerable_results),
        unanswerable_cases=len(unanswerable_results),
        source_hit_rate=_mean_bool(result.hit for result in answerable_results),
        mean_precision_at_k=_mean(result.precision_at_k for result in answerable_results),
        mean_recall_at_k=_mean(result.recall_at_k for result in answerable_results),
        mean_reciprocal_rank=_mean(
            result.reciprocal_rank for result in answerable_results
        ),
        mean_ndcg_at_k=_mean(result.ndcg_at_k for result in answerable_results),
        empty_result_rate=_mean_bool(result.result_count == 0 for result in results),
        unanswerable_nonempty_rate=_mean_bool(
            result.result_count > 0 for result in unanswerable_results
        ),
        forbidden_source_leakage_rate=_mean_bool(
            result.forbidden_source_leakage for result in results
        ),
        scenario_summaries=_scenario_summaries(results),
        results=results,
    )


def _scenario_summaries(
    results: tuple[RagEvalResult, ...],
) -> dict[str, dict[str, float | int]]:
    grouped: dict[str, list[RagEvalResult]] = {}
    for result in results:
        grouped.setdefault(result.case.scenario, []).append(result)
    summaries: dict[str, dict[str, float | int]] = {}
    for scenario, group in sorted(grouped.items()):
        answerable = [result for result in group if result.case.answerable]
        unanswerable = [result for result in group if not result.case.answerable]
        summaries[scenario] = {
            "cases": len(group),
            "answerable_cases": len(answerable),
            "unanswerable_cases": len(unanswerable),
            "source_hit_rate": _mean_bool(result.hit for result in answerable),
            "mean_precision_at_k": _mean(result.precision_at_k for result in answerable),
            "mean_recall_at_k": _mean(result.recall_at_k for result in answerable),
            "mean_reciprocal_rank": _mean(
                result.reciprocal_rank for result in answerable
            ),
            "mean_ndcg_at_k": _mean(result.ndcg_at_k for result in answerable),
            "forbidden_source_leakage_rate": _mean_bool(
                result.forbidden_source_leakage for result in group
            ),
            "unanswerable_nonempty_rate": _mean_bool(
                result.result_count > 0 for result in unanswerable
            ),
        }
    return summaries


def _unique_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    unique: list[str] = []
    for source in sources:
        normalized = source.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(source)
    return tuple(unique)


def _mean(values: Iterable[float]) -> float:
    resolved = list(values)
    if not resolved:
        return 0.0
    return round(sum(resolved) / len(resolved), 6)


def _mean_bool(values: Iterable[bool]) -> float:
    resolved = list(values)
    if not resolved:
        return 0.0
    return round(sum(1 for value in resolved if value) / len(resolved), 6)


def _ndcg_at_k(
    retrieved_sources: tuple[str, ...],
    expected_sources: tuple[str, ...],
    top_k: int,
) -> float:
    if not expected_sources or top_k <= 0:
        return 0.0
    seen_sources: set[str] = set()
    gains: list[float] = []
    for source in retrieved_sources[:top_k]:
        normalized = source.replace("\\", "/")
        if normalized in seen_sources:
            gains.append(0.0)
            continue
        seen_sources.add(normalized)
        gains.append(1.0 if _matches_expected_source(source, expected_sources) else 0.0)
    dcg = _discounted_cumulative_gain(gains)
    ideal_relevant = min(len(expected_sources), top_k)
    ideal_dcg = _discounted_cumulative_gain([1.0] * ideal_relevant)
    return dcg / ideal_dcg if ideal_dcg else 0.0


def _discounted_cumulative_gain(gains: list[float]) -> float:
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
