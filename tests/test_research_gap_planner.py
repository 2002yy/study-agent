from __future__ import annotations

import pytest

from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchClaim,
)
from src.web.research.gap_planner import (
    GapSearchIntent,
    focus_claim_surface,
    plan_gap_queries,
)


def _claim(
    text: str,
    *,
    roles: tuple[str, ...] = ("primary",),
    requires_primary: bool = True,
    dated: bool = False,
) -> ResearchClaim:
    return ResearchClaim(
        id="claim-1",
        question_id="question-1",
        text=text,
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=roles,
            min_independent_sources=1,
            requires_primary_source=requires_primary,
            requires_successful_read=True,
            max_age_days=30 if dated else None,
            requires_dated_evidence=dated,
        ),
    )


def _gap(*, role: str = "primary", gap_type: str = "evidence_shortfall") -> EvidenceGap:
    return EvidenceGap(
        id="gap-1",
        claim_id="claim-1",
        gap_type=gap_type,
        desired_source_role=role,
        priority="critical",
        state="open",
    )


def test_focused_query_removes_question_scaffolding_not_key_terms() -> None:
    focused = focus_claim_surface(
        "What is the current official primary rate limit for unauthenticated "
        "requests to the GitHub REST API?"
    )
    assert focused == "rate limit unauthenticated requests GitHub REST API"
    assert "What is the current" not in focused


def test_chinese_query_uses_focused_surface_and_chinese_intent_suffixes() -> None:
    claim = _claim("请问当前 GitHub REST API 未认证请求的官方限额是多少？", dated=True)
    batch = plan_gap_queries(_gap(), claim, reference_date="2026-08-27")
    assert "请问" not in batch.focused_surface
    assert "当前" not in batch.focused_surface
    assert "是多少" not in batch.focused_surface
    assert "官方文档" in batch.queries[1].query


def test_primary_gap_produces_four_distinct_intents_and_queries() -> None:
    batch = plan_gap_queries(
        _gap(),
        _claim(
            "What is the current official primary rate limit for unauthenticated "
            "requests to the GitHub REST API?",
            dated=True,
        ),
        reference_date="2026-08-27",
    )

    assert len(batch.queries) == 4
    assert [item.intent for item in batch.queries] == [
        GapSearchIntent.DISCOVERY,
        GapSearchIntent.PRIMARY,
        GapSearchIntent.PROVENANCE,
        GapSearchIntent.VERIFICATION,
    ]
    assert len({item.query.casefold() for item in batch.queries}) == 4
    assert "2026" in batch.queries[0].query
    assert "official docs" in batch.queries[1].query
    assert all("What is the current" not in item.query for item in batch.queries)


def test_community_gap_requests_community_and_verification_intents() -> None:
    batch = plan_gap_queries(
        _gap(role="community"),
        _claim(
            "How do Python developers describe free-threaded Python 3.13?",
            roles=("community", "independent_secondary"),
            requires_primary=False,
        ),
        max_queries=3,
    )
    assert [item.intent for item in batch.queries] == [
        GapSearchIntent.DISCOVERY,
        GapSearchIntent.COMMUNITY,
        GapSearchIntent.VERIFICATION,
    ]


def test_counter_evidence_gap_includes_explicit_counter_intent() -> None:
    batch = plan_gap_queries(
        _gap(role="independent_secondary", gap_type="conflict_unresolved"),
        _claim("The claimed cause of the outage is correct.", requires_primary=False),
    )
    assert batch.queries[-1].intent == GapSearchIntent.COUNTER_EVIDENCE


def test_planner_enforces_bounds_and_gap_ownership() -> None:
    assert len(plan_gap_queries(_gap(), _claim("FastAPI license"), max_queries=1).queries) == 2
    assert len(plan_gap_queries(_gap(), _claim("FastAPI license"), max_queries=99).queries) == 4
    bad_gap = EvidenceGap(
        id="gap-other",
        claim_id="other-claim",
        gap_type="evidence_shortfall",
        state="open",
    )
    with pytest.raises(ValueError, match="claim_id"):
        plan_gap_queries(bad_gap, _claim("FastAPI license"))


def test_non_primary_requirement_does_not_generate_primary_intent() -> None:
    batch = plan_gap_queries(
        _gap(role="independent_secondary"),
        _claim(
            "Confidential partnership terms are not publicly verifiable.",
            roles=("independent_secondary",),
            requires_primary=False,
        ),
    )
    assert GapSearchIntent.PRIMARY not in {item.intent for item in batch.queries}
