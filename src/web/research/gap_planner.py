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

# Query Construction Hardening: deterministic normalisation only (no LLM query
# rewriter). A gap query must be a standalone search expression, not a slice of
# the claim's grammar.
_QUERY_FRAGMENT_TOKENS = frozenset(
    {
        # pronouns / demonstratives
        "it", "its", "it's", "that", "this", "these", "those", "they", "them",
        "their", "theirs", "he", "him", "his", "she", "her", "hers", "we",
        "us", "our", "ours", "you", "your", "yours", "i", "me", "my", "mine",
        # auxiliaries / copulas
        "is", "are", "was", "were", "be", "been", "being", "am", "do", "does",
        "did", "done", "has", "have", "had", "will", "would", "shall",
        "should", "can", "could", "may", "might", "must",
        # question words
        "what", "which", "when", "where", "who", "whom", "whose", "how",
        "why", "whether",
        # determiners / quantifiers
        "a", "an", "the", "some", "any", "each", "every", "no", "all", "both",
        "few", "many", "much", "more", "most", "other", "such",
        # conjunctions / subordinators
        "and", "or", "but", "nor", "so", "yet", "if", "then", "than", "as",
        "because", "while", "although", "though", "since", "unless", "until",
        # prepositions that never anchor an entity (keep "of" for entity names)
        "on", "in", "at", "to", "from", "by", "for", "with", "about", "into",
        "over", "after", "before", "during", "between", "without", "under",
        # fillers / discourse / claim-surface scaffolding
        "according", "recent", "recently", "current", "currently", "now",
        "also", "just", "very", "really", "actually", "still", "already",
        "please", "however", "therefore", "thus", "hence", "not", "official",
        "documentation", "docs", "accordingly", "respectively",
    }
)

_QUERY_SOURCE_ANCHORS_PLACEHOLDER = None

_QUERY_MAX_TOKENS = 14

# Leading generic temporal nouns that cannot carry a query when no entity anchor
# exists (audit fixtures: "month it cover", "on date was that decision announced").
_QUERY_WEAK_LEAD_TOKENS = frozenset({"date", "month", "year", "time", "day", "week"})


class GapSearchIntent(StrEnum):
    DISCOVERY = "discovery"
    PRIMARY = "primary"
    PROVENANCE = "provenance"
    VERIFICATION = "verification"
    COMMUNITY = "community"
    COUNTER_EVIDENCE = "counter_evidence"


_QUERY_SOURCE_ANCHORS: dict[GapSearchIntent, str] = {
    GapSearchIntent.PRIMARY: "official docs",
    GapSearchIntent.PROVENANCE: "announcement",
    GapSearchIntent.VERIFICATION: "independent verification",
    GapSearchIntent.COMMUNITY: "discussion",
    GapSearchIntent.COUNTER_EVIDENCE: "correction",
}

_QUERY_SOURCE_ANCHORS_ZH: dict[GapSearchIntent, str] = {
    GapSearchIntent.PRIMARY: "官方文档",
    GapSearchIntent.PROVENANCE: "公告",
    GapSearchIntent.VERIFICATION: "独立验证",
    GapSearchIntent.COMMUNITY: "讨论",
    GapSearchIntent.COUNTER_EVIDENCE: "更正",
}


@dataclass(frozen=True)
class PlannedGapQuery:
    id: str
    gap_id: str
    claim_id: str
    intent: GapSearchIntent
    query: str
    desired_source_role: str = ""
    # Query Construction Hardening: False when the surface had no entity anchor
    # (the query is still deterministic, but the trace can see it).
    anchored: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gap_id": self.gap_id,
            "claim_id": self.claim_id,
            "intent": self.intent.value,
            "query": self.query,
            "desired_source_role": self.desired_source_role,
            "anchored": self.anchored,
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
    trusted_domain: str = "",
    question: str = "",
) -> GapQueryBatch:
    """Return a bounded, intent-diverse query batch for one open gap.

    Query Construction Hardening: a query is composed from explicit anchors
    (``subject_anchor`` + ``fact_anchor`` + one ``source_anchor``) rather than
    from the claim's grammar. Deterministic normalisation only - no LLM query
    rewriter. ``question`` (the original question) is the preferred surface when
    available, because claim text can be a grammar fragment with no entity.

    ``source_hints`` are bounded research hints (organizations, official
    terminology, follow-up terms). They only sharpen wording.

    ``trusted_domain`` is the ONLY source of a ``site:`` constraint: ``site:`` is
    a strong restriction, so it is used only when the caller has a reason to
    believe the domain *is* the evidence owner (Slice 2B discovered domains, or
    a page whose server-owned source role is ``primary``). A mere source domain
    must never be converted into a ``site:`` constraint - that would lock the
    follow-up search into a mirror/aggregator domain.
    """

    if gap.claim_id != claim.id:
        raise ValueError("gap claim_id does not match research claim")
    if gap.state not in {"open", "searching"}:
        raise ValueError("only open/searching gaps can produce query batches")
    limit = max(MIN_QUERIES_PER_GAP, min(int(max_queries), MAX_QUERIES_PER_GAP))
    # The claim surface supplies the claim-specific fact; the question surface
    # only supplies the entity when the claim text lost it (grammar fragments
    # such as "on date was that decision announced"). Mixing them this way keeps
    # distinct claims on distinct queries while still anchoring on an entity.
    claim_surface = " ".join(str(claim.text or "").split())
    question_surface = " ".join(str(question or "").split())
    claim_subject, claim_fact, claim_anchored = _query_anchors(claim_surface)
    if claim_anchored:
        subject_anchor, fact_anchor, anchored = claim_subject, claim_fact, True
    else:
        question_subject, question_fact, question_anchored = _query_anchors(
            question_surface
        )
        if question_anchored:
            subject_anchor = question_subject
            fact_anchor = claim_fact or question_fact
            anchored = True
        else:
            subject_anchor = ""
            fact_anchor = claim_fact or question_fact
            anchored = False
    surface_text = f"{subject_anchor} {fact_anchor}".strip() or claim_surface
    if re.search(r"[\u3400-\u9fff]", f"{claim_surface} {question_surface}"):
        # CJK surfaces keep the existing deterministic focused-surface path; the
        # ASCII anchor splitter cannot segment Chinese reliably.
        subject_anchor, fact_anchor, anchored = "", "", False
        content_tokens: tuple[str, ...] = ()
        focused = focus_claim_surface(claim.text)
    else:
        content_tokens = _query_content_tokens(surface_text)
        focused = " ".join(content_tokens) or focus_claim_surface(claim.text)
    temporal = bool(_TEMPORAL_PATTERN.search(surface_text)) or (
        claim.evidence_requirement.requires_dated_evidence
        or claim.evidence_requirement.max_age_days is not None
    )
    year = _reference_year(reference_date) if temporal else ""
    hints = _bounded_hints(source_hints)
    trusted = _bounded_domain(trusted_domain)
    intents = _select_intents(gap=gap, claim=claim)[:limit]
    queries: list[PlannedGapQuery] = []
    seen: set[str] = set()
    for intent in intents:
        query = _query_for_intent(
            subject_anchor=subject_anchor,
            fact_anchor=fact_anchor,
            fallback_surface=focused,
            intent=intent,
            desired_source_role=gap.desired_source_role,
            reference_year=year,
            source_hints=hints,
            trusted_domain=trusted,
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
                anchored=anchored,
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
    *,
    subject_anchor: str,
    fact_anchor: str,
    fallback_surface: str,
    intent: GapSearchIntent,
    desired_source_role: str,
    reference_year: str,
    source_hints: tuple[str, ...] = (),
    trusted_domain: str = "",
) -> str:
    """Compose one search expression from explicit anchors.

    Order is ``subject_anchor + fact_anchor + one source_anchor (+ year)``. The
    source anchor is a single bounded phrase chosen by intent - suffixes are
    never stacked, because stacking dilutes the entity and does not make a
    search engine prefer primary sources.

    A ``site:`` constraint is only emitted from an explicit ``trusted_domain``
    (evidence owner), never from a hint string that merely looks like a domain.
    """

    parts: list[str] = []
    if subject_anchor:
        parts.append(subject_anchor)
    if fact_anchor:
        parts.append(fact_anchor)
    elif not subject_anchor:
        # No anchors at all: keep the deterministic normalised surface so the
        # query is still a standalone expression, never a raw grammar slice.
        parts.append(fallback_surface)

    source_anchor = (
        _QUERY_SOURCE_ANCHORS_ZH
        if re.search(r"[\u3400-\u9fff]", f"{subject_anchor}{fact_anchor}{fallback_surface}")
        else _QUERY_SOURCE_ANCHORS
    ).get(intent, "")
    term_hint = _first_term_hint(source_hints)
    if (
        intent in {GapSearchIntent.PRIMARY, GapSearchIntent.PROVENANCE}
        and trusted_domain
    ):
        # A discovered/verified evidence-owner domain is the strongest anchor.
        parts.append(f"site:{trusted_domain}")
        if term_hint:
            parts.append(term_hint)
    elif source_anchor:
        parts.append(source_anchor)
        if (
            desired_source_role == "primary"
            and intent == GapSearchIntent.PRIMARY
            and term_hint
        ):
            parts.append(term_hint)

    if reference_year and intent in {
        GapSearchIntent.DISCOVERY,
        GapSearchIntent.PRIMARY,
        GapSearchIntent.VERIFICATION,
    }:
        parts.append(reference_year)

    tokens = _dedupe_query_tokens(" ".join(parts))
    return " ".join(tokens[:_QUERY_MAX_TOKENS]).strip()[:1200]


def _bounded_domain(value: str) -> str:
    """Return a site-worthy domain, or "" when the value is not a domain."""

    text = str(value or "").strip().casefold()
    if not text:
        return ""
    text = text.split("//")[-1].split("/")[0].strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}", text):
        return ""
    return text[:253]


def _looks_like_domain(value: str) -> bool:
    return bool(_bounded_domain(value))


def _first_term_hint(source_hints: tuple[str, ...]) -> str:
    """First non-domain hint, bounded (domains are never search terms here)."""

    for hint in source_hints:
        if _looks_like_domain(hint):
            continue
        text = " ".join(str(hint or "").split())[:120]
        if text:
            return text
    return ""


def query_terms(text: str) -> tuple[str, ...]:
    """Public wrapper: deterministic content tokens (fragments removed).

    Used for hint/term extraction outside the planner (e.g. evidence-lead
    follow-up hints) so the same fragment rules apply everywhere.
    """

    return _query_content_tokens(text)


def _query_content_tokens(text: str) -> tuple[str, ...]:
    """Deterministic content tokens: fragments/pronouns/auxiliaries removed."""

    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.\-]*", str(text or "")):
        token = raw_token.strip("'&.-")
        if token.casefold().endswith("'s"):
            token = token[:-2]
        if not token:
            continue
        key = token.casefold()
        if key in _QUERY_FRAGMENT_TOKENS or len(token) < 2:
            continue
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)
    return tuple(tokens)


def _query_anchors(text: str) -> tuple[str, str, bool]:
    """Return ``(subject_anchor, fact_anchor, anchored)``.

    The subject anchor is the longest capitalised token run (an entity such as
    ``Docker Hub`` or ``Bank of England``). The fact anchor is the remaining
    content tokens. ``anchored`` is False when no entity run exists, so the
    trace can separate "weak surface" from "bad normalisation".
    """

    raw_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.\-]*", str(text or ""))
    runs: list[list[str]] = []
    current: list[str] = []
    connectors = {"of", "the", "and", "for", "de", "van", "der"}
    for index, token in enumerate(raw_tokens):
        clean = token.strip("'&.-")
        if not clean:
            continue
        key = clean.casefold()
        is_capitalised = clean[:1].isupper() and key not in _QUERY_FRAGMENT_TOKENS
        is_connector = key in connectors and current
        if is_capitalised or is_connector:
            if index == 0 and not current and is_capitalised and not is_connector:
                # Sentence-initial capitalisation alone is not an entity.
                continue
            current.append(clean)
            continue
        if current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    runs = [run for run in runs if len(run) >= 2 or (run and run[0][:1].isupper())]

    subject = ""
    subject_keys: set[str] = set()
    if runs:
        best = max(runs, key=len)
        subject = " ".join(best)
        subject_keys = {token.casefold() for token in best}
    fact_tokens = [
        token
        for token in _query_content_tokens(text)
        if token.casefold() not in subject_keys and token.casefold() != "of"
    ]
    if not subject:
        # No entity anchor: a leading generic temporal noun ("month", "date") is
        # exactly the grammar fragment the audit found, so drop it rather than
        # let it carry the query.
        while fact_tokens and fact_tokens[0].casefold() in _QUERY_WEAK_LEAD_TOKENS:
            fact_tokens.pop(0)
    fact = " ".join(fact_tokens[: _QUERY_MAX_TOKENS - 4])
    return subject, fact, bool(subject)


def _dedupe_query_tokens(text: str) -> tuple[str, ...]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in re.findall(
        r"[A-Za-z0-9\u3400-\u9fff][A-Za-z0-9'&.\-:\u3400-\u9fff]*",
        str(text or ""),
    ):
        token = raw_token.strip("'&.-")
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        tokens.append(token)
    return tuple(tokens)


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
