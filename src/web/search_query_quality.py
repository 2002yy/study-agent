"""Fallback-search quality helpers (Fallback Search-1B).

Pure, side-effect-free building blocks for the bounded recovery path:
- ``optimize_search_query`` de-weights generic CJK scaffolding from *search
  advice* while preserving entities, versions, dates and conditions;
- ``order_candidates`` gives a composite ordering that never trusts the
  related-target count alone;
- ``classify_candidate`` labels a candidate relevant / off_target / unknown
  for retrieval scheduling only (never answer support).

Wiring these into ``research_recovery._recover_public_research`` is done in a
separate, carefully typed pass; this module grants no evidence or publication
authority.
"""

from __future__ import annotations

import re
from typing import Any

# Generic scaffolding that makes a fallback engine match the literal word
# ("比较") instead of the entity/version. Only removed when it is its own
# whitespace-separated token, so an entity named with such a substring survives.
GENERIC_QUERY_TOKENS = frozenset(
    {
        "比较", "对比", "区别", "区别？", "优缺点", "如何", "为什么", "为什么？", "是否",
        "以及", "并且", "分别", "哪些", "什么", "介绍", "解释", "说明", "区分", "条件",
        "适用", "应该", "可能", "需要", "研究", "分析", "总结", "主要", "相关", "更",
    }
)


def optimize_search_query(task_query: str) -> tuple[str, str]:
    """Return (optimized_query, reason); fall back to the original on no change."""
    original = task_query or ""
    tokens = [token for token in re.split(r"\s+", original.strip()) if token]
    kept = [token for token in tokens if token not in GENERIC_QUERY_TOKENS]
    optimized = " ".join(kept).strip()
    if not optimized or len(kept) == len(tokens):
        return original, "unchanged"
    return optimized, f"generic_tokens_removed:{len(tokens) - len(kept)}"


def order_candidates(
    candidates: list[dict[str, Any]],
    *,
    relevance_by_url: dict[str, list[str]],
    markers: list[re.Pattern[str]],
) -> list[dict[str, Any]]:
    """Composite ordering: relevance strength -> entity/condition match ->
    expected independent coverage -> original search rank.

    The related-target count is one signal only; it never proves body relevance
    or answer support.
    """

    def key(entry: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        index, row = entry
        assessment = row.get("assessment") or {}
        item = row.get("item") or {}
        url = str(assessment.get("url", "")) if isinstance(assessment, dict) else ""
        related = len(relevance_by_url.get(url, []))
        text = f"{item.get('title', '')} {item.get('snippet', '')} {url}"
        entity = 1 if any(marker.search(text) for marker in markers) else 0
        return (-(1 if related else 0), -entity, -related, index)

    return [row for _, row in sorted(enumerate(candidates), key=key)]


def classify_candidate(*, related_ids: list[str], judged: bool) -> str:
    """relevant / off_target / unknown. UNKNOWN is never auto-deleted."""
    if related_ids:
        return "relevant"
    if judged:
        return "off_target"
    return "unknown"
