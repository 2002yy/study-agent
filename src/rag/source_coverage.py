from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from src.rag.schema import RagIndex, RagSearchResult
from src.rag.service import RagSearchDiagnostics, search_documents_with_debug


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
    Composite questions widen candidate retrieval first, then admit at most one
    final chunk per source so a dominant document cannot crowd out a second source.
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


def _select_diverse_results(
    results: list[RagSearchResult],
    *,
    top_k: int,
    max_chunks_per_source: int,
) -> tuple[list[RagSearchResult], int]:
    if max_chunks_per_source <= 0:
        return results[:top_k], 0
    selected: list[RagSearchResult] = []
    source_counts: dict[str, int] = {}
    suppressed = 0
    for result in results:
        source_key = result.chunk.document_id or result.chunk.source_path
        if source_counts.get(source_key, 0) >= max_chunks_per_source:
            suppressed += 1
            continue
        selected.append(result)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        if len(selected) >= top_k:
            break
    return selected, suppressed


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
    selected, suppressed = _select_diverse_results(
        expanded.results,
        top_k=top_k,
        max_chunks_per_source=plan.effective_max_chunks_per_source,
    )
    debug = {
        **expanded.debug,
        "returned_count": len(selected),
        "results": [
            item
            for item in expanded.debug.get("results", [])
            if item.get("chunk_id") in {result.chunk.chunk_id for result in selected}
        ],
        "source_coverage": {
            **plan.to_dict(),
            "expanded_candidate_k": candidate_k,
            "expanded_result_count": len(expanded.results),
            "selected_result_count": len(selected),
            "source_diversity_suppressed": suppressed,
        },
    }
    return RagSearchDiagnostics(results=selected, debug=debug)
