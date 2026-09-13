"""Deterministic SearchIntent planning for one Claim Engine evidence gap.

This is deliberately separate from :mod:`src.web.query_router`, whose
``SearchIntent`` describes top-level topics such as news or source code.  A
``GapSearchIntent`` describes why one query exists inside a research batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import re
from typing import Any

from src.web.research.contracts import EvidenceGap, ResearchClaim

MIN_QUERIES_PER_GAP = 2
DEFAULT_QUERIES_PER_GAP = 4
MAX_QUERIES_PER_GAP = 4


class GapSearchIntent(StrEnum):
    DISCOVERY = "discovery"
    PRIMARY = "primary"
    PROVENANCE = "provenance"
    VERIFICATION = "verification"
    COMMUNITY = "community"
    COUNTER_EVIDENCE = "counter_evidence"


@dataclass(frozen=True)
class PlannedGapQuery:
    id: str
    gap_id: str
    claim_id: str
    intent: GapSearchIntent
    query: str
    desired_source_role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gap_id": self.gap_id,
            "claim_id": self.claim_id,
            "intent": self.intent.value,
            "query": self.query,
            "desired_source_role": self.desired_source_role,
        }


@dataclass(frozen=True)
class GapQueryBatch:
    gap_id: str
    claim_id: str
    focused_surface: str
    queries: tuple[PlannedGapQuery, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "claim_id": self.claim_id,
            "focused_surface": self.focused_surface,
            "queries": [item.to_dict() for item in self.queries],
        }


_TOKEN_PATTERN = re.compile(r"[\w.+#/-]+", re.UNICODE)
_TEMPORAL_PATTERN = re.compile(
    r"\b(current|currently|latest|most recent|recent|today|now)\b|"
    r"最新|当前|最近|今日|今天",
    re.IGNORECASE,
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "according",
    "be",
    "can",
    "current",
    "currently",
    "did",
    "do",
    "does",
    "exact",
    "for",
    "from",
    "how",
    "in",
    "is",
    "latest",
    "most",
    "of",
    "official",
    "primary",
    "published",
    "the",
    "their",
    "to",
    "what",
    "when",
    "which",
    "why",
    "will",
    "with",
    "请",
    "帮我",
    "联网",
    "搜索",
    "查询",
    "是什么",
    "为什么",
    "如何",
    "当前",
    "最新",
}
_CHINESE_SCAFFOLD = (
    "请问",
    "请帮我",
    "帮我",
    "我想知道",
    "联网研究",
    "联网搜索",
    "搜索一下",
    "查询一下",
    "是什么",
    "是多少",
    "有哪些",
    "如何",
    "为什么",
    "怎么",
    "当前",
    "最新",
    "官方",
)


def focus_claim_surface(surface: str) -> str:
    """Remove generic question scaffolding while preserving answer-bearing terms."""

    prepared = " ".join(str(surface or "").split())
    for scaffold in _CHINESE_SCAFFOLD:
        prepared = prepared.replace(scaffold, " ")
    tokens = _TOKEN_PATTERN.findall(prepared)
    focused = [token for token in tokens if token.casefold() not in _STOPWORDS]
    value = " ".join(focused).strip()
    if value:
        return value[:1000]
    fallback = " ".join(str(surface or "").split()).strip()
    if not fallback:
        raise ValueError("claim surface is required for gap query planning")
    return fallback[:1000]


def plan_gap_queries(
    gap: EvidenceGap,
    claim: ResearchClaim,
    *,
    reference_date: str = "",
    max_queries: int = DEFAULT_QUERIES_PER_GAP,
    source_hints: tuple[str, ...] = (),
) -> GapQueryBatch:
    """Return a bounded, intent-diverse query batch for one open gap.

    ``source_hints`` are bounded lead-discovery hints (domains, organizations,
    official terminology). They only influence how this planner words its own
    queries - the Gap Planner remains the single query-strategy owner, and a
    hint can never mint a candidate or change evidence eligibility.
    """

    if gap.claim_id != claim.id:
        raise ValueError("gap claim_id does not match research claim")
    if gap.state not in {"open", "searching"}:
        raise ValueError("only open/searching gaps can produce query batches")
    limit = max(MIN_QUERIES_PER_GAP, min(int(max_queries), MAX_QUERIES_PER_GAP))
    focused = focus_claim_surface(claim.text)
    temporal = bool(_TEMPORAL_PATTERN.search(claim.text)) or (
        claim.evidence_requirement.requires_dated_evidence
        or claim.evidence_requirement.max_age_days is not None
    )
    year = _reference_year(reference_date) if temporal else ""
    hints = _bounded_hints(source_hints)
    intents = _select_intents(gap=gap, claim=claim)[:limit]
    queries: list[PlannedGapQuery] = []
    seen: set[str] = set()
    for intent in intents:
        query = _query_for_intent(
            focused,
            intent=intent,
            desired_source_role=gap.desired_source_role,
            reference_year=year,
            source_hints=hints,
        )
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(
            PlannedGapQuery(
                id=f"{gap.id}:{intent.value}",
                gap_id=gap.id,
                claim_id=claim.id,
                intent=intent,
                query=query,
                desired_source_role=gap.desired_source_role,
            )
        )
    if len(queries) < MIN_QUERIES_PER_GAP:
        raise ValueError("gap planner failed to produce two distinct intent queries")
    return GapQueryBatch(
        gap_id=gap.id,
        claim_id=claim.id,
        focused_surface=focused,
        queries=tuple(queries),
    )


def _select_intents(
    *,
    gap: EvidenceGap,
    claim: ResearchClaim,
) -> tuple[GapSearchIntent, ...]:
    gap_type = gap.gap_type.casefold()
    role = gap.desired_source_role.casefold()
    profile_roles = set(claim.evidence_requirement.source_roles)
    conflict_like = any(
        marker in gap_type for marker in ("conflict", "contradict", "counter")
    )
    if role == "community" or profile_roles == {"community", "independent_secondary"}:
        return (
            GapSearchIntent.DISCOVERY,
            GapSearchIntent.COMMUNITY,
            GapSearchIntent.VERIFICATION,
            GapSearchIntent.COUNTER_EVIDENCE,
        )
    if conflict_like:
        second = (
            GapSearchIntent.PRIMARY
            if "primary" in profile_roles
            else GapSearchIntent.PROVENANCE
        )
        return (
            GapSearchIntent.DISCOVERY,
            second,
            GapSearchIntent.VERIFICATION,
            GapSearchIntent.COUNTER_EVIDENCE,
        )
    if role == "primary" or claim.evidence_requirement.requires_primary_source:
        return (
            GapSearchIntent.DISCOVERY,
            GapSearchIntent.PRIMARY,
            GapSearchIntent.PROVENANCE,
            GapSearchIntent.VERIFICATION,
        )
    if "primary" not in profile_roles:
        return (
            GapSearchIntent.DISCOVERY,
            GapSearchIntent.PROVENANCE,
            GapSearchIntent.VERIFICATION,
            GapSearchIntent.COUNTER_EVIDENCE,
        )
    return (
        GapSearchIntent.DISCOVERY,
        GapSearchIntent.PRIMARY,
        GapSearchIntent.PROVENANCE,
        GapSearchIntent.VERIFICATION,
    )


def _query_for_intent(
    focused: str,
    *,
    intent: GapSearchIntent,
    desired_source_role: str,
    reference_year: str,
    source_hints: tuple[str, ...] = (),
) -> str:
    suffixes = (
        {
            GapSearchIntent.DISCOVERY: "",
            GapSearchIntent.PRIMARY: "官方文档",
            GapSearchIntent.PROVENANCE: "原始来源 公告",
            GapSearchIntent.VERIFICATION: "独立验证",
            GapSearchIntent.COMMUNITY: "社区 使用体验",
            GapSearchIntent.COUNTER_EVIDENCE: "反例 纠正 矛盾证据",
        }
        if re.search(r"[\u3400-\u9fff]", focused)
        else {
            GapSearchIntent.DISCOVERY: "",
            GapSearchIntent.PRIMARY: "official documentation",
            GapSearchIntent.PROVENANCE: "original source announcement",
            GapSearchIntent.VERIFICATION: "independent verification",
            GapSearchIntent.COMMUNITY: "community experience discussion",
            GapSearchIntent.COUNTER_EVIDENCE: "contradiction correction counter evidence",
        }
    )
    parts = [focused, suffixes[intent]]
    if desired_source_role == "primary" and intent == GapSearchIntent.PRIMARY:
        parts.append("primary source")
    # Lead-discovery hints only sharpen primary/provenance query wording.
    if source_hints and intent in {
        GapSearchIntent.PRIMARY,
        GapSearchIntent.PROVENANCE,
    }:
        site_hint, term_hint = _hint_fragments(source_hints)
        if site_hint:
            parts.append(f"site:{site_hint}")
        if term_hint:
            parts.append(term_hint)
    if reference_year and intent in {
        GapSearchIntent.DISCOVERY,
        GapSearchIntent.PRIMARY,
        GapSearchIntent.VERIFICATION,
    }:
        parts.append(reference_year)
    return " ".join(part for part in parts if part).strip()[:1200]


def _bounded_hints(source_hints: tuple[str, ...]) -> tuple[str, ...]:
    """Bound and normalize lead-discovery hints before they reach a query."""

    bounded: list[str] = []
    for raw in source_hints:
        hint = " ".join(str(raw or "").split())[:120]
        if not hint or hint in bounded:
            continue
        bounded.append(hint)
        if len(bounded) >= 4:
            break
    return tuple(bounded)


def _hint_fragments(source_hints: tuple[str, ...]) -> tuple[str, str]:
    """Return one site hint and one terminology hint, in that priority."""

    site = ""
    term = ""
    for hint in source_hints:
        if not site and re.fullmatch(r"[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", hint):
            site = hint.casefold()
            continue
        if not term:
            term = hint
    return site, term


def _reference_year(value: str) -> str:
    if not value:
        return ""
    try:
        return str(date.fromisoformat(value).year)
    except ValueError as exc:
        raise ValueError("reference_date must be an ISO date") from exc


__all__ = [
    "DEFAULT_QUERIES_PER_GAP",
    "GapQueryBatch",
    "GapSearchIntent",
    "MAX_QUERIES_PER_GAP",
    "MIN_QUERIES_PER_GAP",
    "PlannedGapQuery",
    "focus_claim_surface",
    "plan_gap_queries",
]
