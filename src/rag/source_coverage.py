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
    facet_top_k: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def plan_source_coverage(
    query: str,
    *,
    top_k: int,
    configured_max_chunks_per_source: int,
    adaptive: bool = True,
) -> SourceCoveragePlan:
    """Plan source coverage only for explicit composite questions.

    Normal single-source questions preserve the caller's current retrieval behavior.
    Composite questions keep every unique source already present in the ordinary
    top-K and use only duplicate-source slots to add facet-specific evidence.
    """
    if not adaptive or top_k <= 1:
        return SourceCoveragePlan(
            enabled=False,
            reason="disabled" if not adaptive else "top_k_too_small",
            effective_max_chunks_per_source=configured_max_chunks_per_source,
            facet_top_k=1,
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
            facet_top_k=1,
        )

    return SourceCoveragePlan(
        enabled=True,
        reason=matched_reason,
        effective_max_chunks_per_source=1,
        facet_top_k=max(2, min(4, top_k)),
    )


def _source_key(result: RagSearchResult) -> str:
    return result.chunk.document_id or result.chunk.source_path


def _clean_facet(value: str) -> str:
    cleaned = " ".join((value or "").strip().split())
    cleaned = re.sub(r"^[\s,，;；:：]+|[\s?.!。！？,，;；:：]+$", "", cleaned)
    cleaned = re.sub(
        r"^(?:how|what|which|why|when|where)\s+"
        r"(?:do|does|did|should|can|could|would|is|are|was|were)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"^(?:explain|describe)\s+", "", cleaned, flags=re.I)
    return cleaned.strip()


def _dedupe_facets(values: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_facet(value)
        normalized = cleaned.casefold()
        if len(cleaned) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        result.append(cleaned)
    return tuple(result)


def _extract_composite_facets(query: str, reason: str) -> tuple[str, ...]:
    normalized = " ".join((query or "").strip().split())
    if not normalized:
        return ()

    if reason == "while_clauses":
        parts = re.split(r"\bwhile\b", normalized, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            return _dedupe_facets(parts)

    if reason in {"between_clauses", "relationship"}:
        match = re.search(
            r"\bbetween\s+(.+?)\s+and\s+(.+?)(?=\s+(?:so|that|to)\b|[?.!]|$)",
            normalized,
            flags=re.I,
        )
        if match:
            suffix_match = re.search(r"\s+(so|that|to)\b(.+)$", normalized, flags=re.I)
            suffix = suffix_match.group(0) if suffix_match else ""
            return _dedupe_facets([match.group(1), f"{match.group(2)} {suffix}"])

    if reason == "explicit_both":
        match = re.search(
            r"\bboth\s+(.+?)\s+and\s+(.+?)(?:[?.!]|$)",
            normalized,
            flags=re.I,
        )
        if match:
            return _dedupe_facets([match.group(1), match.group(2)])

    if reason == "together":
        match = re.search(
            r"(.+?)\s+and\s+(.+?)\s+(?:work|works)\s+together(.*)$",
            normalized,
            flags=re.I,
        )
        if match:
            suffix = match.group(3)
            return _dedupe_facets([match.group(1), f"{match.group(2)} {suffix}"])

    if reason == "chinese_simultaneous":
        tail = normalized
        if "同时" in tail:
            tail = tail.split("同时", 1)[1]
        parts = re.split(r"[、，,；;]|(?:和|与|及)", tail)
        facets = _dedupe_facets(parts)
        if len(facets) >= 2:
            return facets

    if reason == "across_sources":
        parts = re.split(r"\band\b", normalized, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            return _dedupe_facets(parts)

    return ()


def _unique_base_results(
    results: list[RagSearchResult],
    *,
    top_k: int,
) -> tuple[list[RagSearchResult], int]:
    selected: list[RagSearchResult] = []
    seen_sources: set[str] = set()
    duplicate_count = 0
    for result in results[:top_k]:
        source_key = _source_key(result)
        if source_key in seen_sources:
            duplicate_count += 1
            continue
        seen_sources.add(source_key)
        selected.append(result)
    return selected, duplicate_count


def _selected_debug_results(
    base_debug_results: list[dict],
    selected: list[RagSearchResult],
) -> list[dict]:
    by_chunk_id = {
        str(item.get("chunk_id")): item
        for item in base_debug_results
    }
    rows: list[dict] = []
    for selected_rank, result in enumerate(selected, start=1):
        row = dict(by_chunk_id.get(result.chunk.chunk_id, {}))
        if not row:
            row = result.to_dict()
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
    base = search_documents_with_debug(
        index,
        query,
        top_k=top_k,
        min_score=min_score,
        retrieval_mode=retrieval_mode,
        max_chunks_per_source=(
            configured_max_chunks_per_source if not plan.enabled else 0
        ),
        reranker=reranker,
    )
    if not plan.enabled:
        base.debug["source_coverage"] = plan.to_dict()
        return base

    selected, duplicate_slots = _unique_base_results(base.results, top_k=top_k)
    selected_sources = {_source_key(result) for result in selected}
    facets = _extract_composite_facets(query, plan.reason)
    facet_debug: list[dict[str, object]] = []

    for facet in facets:
        if len(selected) >= top_k:
            break
        diagnostics = search_documents_with_debug(
            index,
            facet,
            top_k=min(len(index.chunks), plan.facet_top_k),
            min_score=min_score,
            retrieval_mode=retrieval_mode,
            max_chunks_per_source=1,
            reranker=reranker,
        )
        champion = diagnostics.results[0] if diagnostics.results else None
        row: dict[str, object] = {
            "facet": facet,
            "result_count": len(diagnostics.results),
        }
        if champion is not None:
            champion_source = _source_key(champion)
            row.update(
                {
                    "champion_source": champion.chunk.source_path,
                    "champion_chunk_id": champion.chunk.chunk_id,
                    "champion_score": round(champion.score, 6),
                    "already_present": champion_source in selected_sources,
                }
            )
            if champion_source not in selected_sources:
                selected.append(champion)
                selected_sources.add(champion_source)
                row["selected"] = True
            else:
                row["selected"] = False
        facet_debug.append(row)

    debug = {
        **base.debug,
        "returned_count": len(selected),
        "results": _selected_debug_results(
            list(base.debug.get("results", [])),
            selected,
        ),
        "source_coverage": {
            **plan.to_dict(),
            "base_result_count": len(base.results),
            "base_unique_source_count": len(selected_sources) - sum(
                1 for row in facet_debug if row.get("selected") is True
            ),
            "duplicate_slots_available": duplicate_slots,
            "facet_queries": list(facets),
            "facet_decisions": facet_debug,
            "selected_result_count": len(selected),
            "non_regression_rule": "preserve_all_unique_base_sources",
        },
    }
    return RagSearchDiagnostics(results=selected, debug=debug)
