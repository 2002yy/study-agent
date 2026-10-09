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
# ("比较") instead of the entity/version. For continuous CJK only the multi-char
# forms are removed inline; single chars are removed only as standalone tokens.
GENERIC_QUERY_TOKENS = frozenset(
    {
        "比较", "对比", "区别", "区别？", "优缺点", "如何", "为什么", "为什么？", "是否",
        "以及", "并且", "分别", "哪些", "什么", "介绍", "解释", "说明", "区分", "条件",
        "适用", "应该", "可能", "需要", "研究", "分析", "总结", "主要", "相关", "更",
        "的", "和", "与", "在", "中", "下", "为", "对", "并",
    }
)
_GENERIC_CJK_INLINE = tuple(
    token for token in GENERIC_QUERY_TOKENS if len(token) >= 2
)
_GENERIC_ENGLISH = frozenset(
    {
        "compare", "comparison", "overview", "introduce", "introduction", "explain",
        "explanation", "guide", "tutorial", "please", "about", "general", "various",
        "using", "based", "main", "mainly", "detail", "details", "information", "info",
        "how", "why", "what", "which", "the", "of", "and", "or", "for", "with", "in",
        "on", "to", "a", "an",
    }
)
MAX_QUERY_TOKENS = 12


def optimize_search_query(task_query: str) -> tuple[str, str]:
    """Return (optimized_query, reason); fall back to the original on no change.

    Handles both whitespace-separated tokens and continuous CJK sentences: removes
    generic scaffolding, keeps entities/versions/dates/negations, and caps length
    so a fallback engine cannot reduce a long query to its first weak token.
    """
    original = task_query or ""
    text = original
    for generic in _GENERIC_CJK_INLINE:
        text = text.replace(generic, " ")
    tokens = [token for token in text.split() if token]
    kept = [
        token
        for token in tokens
        if token not in GENERIC_QUERY_TOKENS and token.casefold() not in _GENERIC_ENGLISH
    ]
    capped = kept[:MAX_QUERY_TOKENS]
    optimized = " ".join(capped).strip()
    if not optimized or optimized == original:
        return original, "unchanged"
    if len(capped) < len(kept):
        return optimized, "generic_and_length_trimmed"
    return optimized, "generic_tokens_removed"


def build_authoritative_query(question: str, domains: tuple[str, ...]) -> str:
    """Build the reserved official query without embedding the whole question.

    Uses the compacted core terms (not the raw sentence) and only prepends a
    known official ``site:`` host; never a bare full-question string.
    """
    compact, _ = optimize_search_query(question)
    if domains:
        return f"site:{domains[0]} {compact}"
    return f"{compact} official documentation"



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
