from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from src.rag.schema import RagIndex
from src.rag.service import RagSearchDiagnostics, search_documents_with_debug


_COMPOSITE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("explicit_both", re.compile(r"\bboth\b", re.I)),
    ("together", re.compile(r"\b(together|combined|combine|combining)\b", re.I)),
    ("across_sources", re.compile(r"\b(across|multiple sources|more than one source)\b", re.I)),
    ("relationship", re.compile(r"\brelationship between\b", re.I)),
    ("chinese_simultaneous", re.compile(r"(同时|结合|两者|分别|多来源|多个来源)")),
)


@dataclass(frozen=True)
class SourceCoveragePlan:
    enabled: bool
    reason: str
    effective_max_chunks_per_source: int

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
    Composite questions use the existing candidate-expansion path but admit at
    most one final chunk per source, preventing one document from crowding out a
    second source required to answer the combined question.
    """
    if not adaptive or top_k <= 1:
        return SourceCoveragePlan(
            enabled=False,
            reason="disabled" if not adaptive else "top_k_too_small",
            effective_max_chunks_per_source=configured_max_chunks_per_source,
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
        )

    return SourceCoveragePlan(
        enabled=True,
        reason=matched_reason,
        effective_max_chunks_per_source=1,
    )


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
