from __future__ import annotations

import re
from dataclasses import asdict, dataclass


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
    Composite questions request a wider candidate pool and at most one final chunk
    per source so one high-scoring document cannot crowd out a second required source.
    """
    if not adaptive or top_k <= 1:
        return SourceCoveragePlan(
            enabled=False,
            reason="disabled" if not adaptive else "top_k_too_small",
            effective_max_chunks_per_source=configured_max_chunks_per_source,
            candidate_multiplier=4,
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
            candidate_multiplier=4,
        )

    return SourceCoveragePlan(
        enabled=True,
        reason=matched_reason,
        effective_max_chunks_per_source=1,
        candidate_multiplier=6,
    )
