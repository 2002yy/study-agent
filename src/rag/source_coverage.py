from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass

from src.rag.index import _document_frequency, _tokenize
from src.rag.schema import RagIndex, RagSearchResult
from src.rag.service import RagSearchDiagnostics, search_documents_with_debug
from src.rag.sufficiency import informative_query_terms


_COMPOSITE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("explicit_both", re.compile(r"\bboth\b", re.I)),
    ("together", re.compile(r"\b(together|combined|combine|combining)\b", re.I)),
    ("across_sources", re.compile(r"\b(across|multiple sources|more than one source)\b", re.I)),
    ("relationship", re.compile(r"\brelationship between\b", re.I)),
    ("between_clauses", re.compile(r"\bbetween\b.+\band\b", re.I)),
    ("while_clauses", re.compile(r"\bwhile\b", re.I)),
    ("chinese_simultaneous", re.compile(r"(同时|结合|两者|分别|多来源|多个来源)")),
)


@dataclass(frozen=True)
class SourceCoveragePlan:
    enabled: bool
    reason: str
    effective_max_chunks_per_source: int
    candidate_multiplier: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def plan_source_coverage(
    query: str,
    *,
    top_k: int,
    configured_max_chunks_per_source: int,
    adaptive: bool = True,
) -> SourceCoveragePlan:
    """Plan source diversity only for explicit composite questions.

    Normal single-source questions preserve the caller's existing source cap.
    Composite questions widen candidate retrieval first, keep the original top-1
    result as a relevance anchor, then add only sources that cover query concepts
    not already explained by selected evidence.
    """
    if not adaptive or top_k <= 1:
        return SourceCoveragePlan(
            enabled=False,
            reason="disabled" if not adaptive else "top_k_too_small",
            effective_max_chunks_per_source=configured_max_chunks_per_source,
            candidate_multiplier=1,
        )

    normalized = " ".join((query or "").strip().split())
    matched_reason = next(
        (
            reason
            for reason, pattern in _COMPOSITE_PATTERNS
            if pattern.search(normalized)
        ),
        "",
    )
    if not matched_reason:
        return SourceCoveragePlan(
            enabled=False,
            reason="single_source_default",
            effective_max_chunks_per_source=configured_max_chunks_per_source,
            candidate_multiplier=1,
        )

    return SourceCoveragePlan(
        enabled=True,
        reason=matched_reason,
        effective_max_chunks_per_source=1,
        candidate_multiplier=8,
    )


def _query_term_weights(index: RagIndex, query: str) -> dict[str, float]:
    query_terms = informative_query_terms(query)
    if not query_terms:
        return {}
    frequencies = _document_frequency(index.chunks)
    total_chunks = max(1, len(index.chunks))
    return {
        term: math.log(
            1.0
            + (total_chunks - frequencies.get(term, 0) + 0.5)
            / (frequencies.get(term, 0) + 0.5)
        )
        for term in query_terms
    }


def _result_query_terms(
    result: RagSearchResult,
    weighted_terms: set[str],
) -> set[str]:
    candidate_terms = set(
        _tokenize(f"{result.chunk.title}\n{result.chunk.text}")
    )
    return candidate_terms & weighted_terms


def _select_coverage_diverse_results(
    index: RagIndex,
    query: str,
    results: list[RagSearchResult],
    *,
    top_k: int,
    max_chunks_per_source: int,
) -> tuple[list[RagSearchResult], int, list[dict[str, object]]]:
    if not results or top_k <= 0:
        return [], 0, []
    if max_chunks_per_source <= 0:
        return results[:top_k], 0, []

    term_weights = _query_term_weights(index, query)
    weighted_terms = set(term_weights)

    # The highest-ranked result remains the relevance anchor. Adaptive coverage
    # may add complementary evidence, but it must not replace the strongest match.
    anchor = results[0]
    selected = [anchor]
    selected_ids = {anchor.chunk.chunk_id}
    anchor_source = anchor.chunk.document_id or anchor.chunk.source_path
    source_counts = {anchor_source: 1}
    covered_terms = _result_query_terms(anchor, weighted_terms)
    decisions: list[dict[str, object]] = [
        {
            "chunk_id": anchor.chunk.chunk_id,
            "source_path": anchor.chunk.source_path,
            "original_rank": 1,
            "selection_reason": "top_rank_anchor",
            "marginal_terms": sorted(covered_terms),
            "marginal_weight": round(
                sum(term_weights.get(term, 0.0) for term in covered_terms),
                6,
            ),
        }
    ]

    while len(selected) < top_k:
        eligible: list[tuple[int, RagSearchResult, set[str], float]] = []
        for rank, result in enumerate(results[1:], start=2):
            if result.chunk.chunk_id in selected_ids:
                continue
            source_key = result.chunk.document_id or result.chunk.source_path
            if source_counts.get(source_key, 0) >= max_chunks_per_source:
                continue
            result_terms = _result_query_terms(result, weighted_terms)
            marginal_terms = result_terms - covered_terms
            marginal_weight = sum(
                term_weights.get(term, 0.0) for term in marginal_terms
            )
            if marginal_weight <= 0:
                continue
            eligible.append((rank, result, marginal_terms, marginal_weight))

        if not eligible:
            break

        rank, chosen, marginal_terms, marginal_weight = max(
            eligible,
            key=lambda item: (item[3], item[1].score, -item[0]),
        )
        source_key = chosen.chunk.document_id or chosen.chunk.source_path
        selected.append(chosen)
        selected_ids.add(chosen.chunk.chunk_id)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        covered_terms.update(_result_query_terms(chosen, weighted_terms))
        decisions.append(
            {
                "chunk_id": chosen.chunk.chunk_id,
                "source_path": chosen.chunk.source_path,
                "original_rank": rank,
                "selection_reason": "marginal_query_coverage",
                "marginal_terms": sorted(marginal_terms),
                "marginal_weight": round(marginal_weight, 6),
            }
        )

    suppressed = max(0, len(results) - len(selected))
    return selected, suppressed, decisions


def _selected_debug_results(
    expanded_results: list[dict],
    selected: list[RagSearchResult],
) -> list[dict]:
    by_chunk_id = {
        str(item.get("chunk_id")): item
        for item in expanded_results
    }
    rows: list[dict] = []
    for selected_rank, result in enumerate(selected, start=1):
        row = dict(by_chunk_id.get(result.chunk.chunk_id, {}))
        if not row:
            continue
        row["original_rank"] = row.get("rank")
        row["rank"] = selected_rank
        rows.append(row)
    return rows


def search_documents_with_adaptive_source_coverage(
    index: RagIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.01,
    retrieval_mode: str = "hybrid",
    configured_max_chunks_per_source: int = 0,
    adaptive: bool = True,
    reranker: str | None = None,
) -> RagSearchDiagnostics:
    plan = plan_source_coverage(
        query,
        top_k=top_k,
        configured_max_chunks_per_source=configured_max_chunks_per_source,
        adaptive=adaptive,
    )
    if not plan.enabled:
        diagnostics = search_documents_with_debug(
            index,
            query,
            top_k=top_k,
            min_score=min_score,
            retrieval_mode=retrieval_mode,
            max_chunks_per_source=plan.effective_max_chunks_per_source,
            reranker=reranker,
        )
        diagnostics.debug["source_coverage"] = plan.to_dict()
        return diagnostics

    candidate_k = min(
        len(index.chunks),
        max(top_k, top_k * plan.candidate_multiplier),
    )
    expanded = search_documents_with_debug(
        index,
        query,
        top_k=candidate_k,
        min_score=min_score,
        retrieval_mode=retrieval_mode,
        max_chunks_per_source=0,
        reranker=reranker,
    )
    selected, suppressed, decisions = _select_coverage_diverse_results(
        index,
        query,
        expanded.results,
        top_k=top_k,
        max_chunks_per_source=plan.effective_max_chunks_per_source,
    )
    debug = {
        **expanded.debug,
        "returned_count": len(selected),
        "results": _selected_debug_results(
            list(expanded.debug.get("results", [])),
            selected,
        ),
        "source_coverage": {
            **plan.to_dict(),
            "expanded_candidate_k": candidate_k,
            "expanded_result_count": len(expanded.results),
            "selected_result_count": len(selected),
            "source_diversity_suppressed": suppressed,
            "selection_decisions": decisions,
        },
    }
    return RagSearchDiagnostics(results=selected, debug=debug)
