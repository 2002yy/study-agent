"""§144 RQ-C: stable evidence-conflict model.

Judgement only: no search, no stop/gate/routing change, no source-count voting.
"""

from __future__ import annotations

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.claim_conflict_assessment import (
    REASON_COUNT_NOT_USED,
    REASON_NO_CONFLICT,
    REASON_TIED_AUTHORITY,
    assess_claim_conflict,
    assess_state_conflicts,
    authority_rank,
    safe_assess_state_conflicts,
)
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.evidence_gate import evaluate_evidence_gate
from src.web.research.stop_gate import evaluate_shadow_stop

_ROLES = (
    "primary",
    "authoritative_secondary",
    "independent_secondary",
    "community",
    "aggregator",
)


def _requirement(*, max_age_days: int | None = None) -> EvidenceRequirement:
    return EvidenceRequirement(
        source_roles=_ROLES,
        min_independent_sources=1,
        requires_primary_source=False,
        requires_successful_read=True,
        max_age_days=max_age_days,
    )


def _state(
    *,
    requirement: EvidenceRequirement | None = None,
    evidence: tuple[ResearchEvidence, ...] = (),
    links: tuple[ResearchClaimEvidenceLink, ...] = (),
    reference_date: str = "",
) -> ResearchState:
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Which side is right?", "critical")],
        claims=[
            ResearchClaim(
                "claim1",
                "q1",
                "A contested factual claim.",
                "factual",
                "critical",
                "searching",
                requirement or _requirement(),
            )
        ],
        evidence=evidence,
        evidence_links=links,
        source_clusters=tuple(
            EvidenceCluster(link.source_cluster_id, (link.evidence_id,)) for link in links
        ),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000),
        reference_date=reference_date,
        known_evidence_ids=tuple(item.evidence_id for item in evidence),
    )


def _evidence(evidence_id: str, *, published_at: str = "") -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id,
        lifecycle_status="read",
        extraction_status="eligible",
        published_at=published_at,
    )


def _link(
    evidence_id: str,
    *,
    relation: str,
    role: str,
    cluster: str,
    strength: float = 0.9,
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("claim1", evidence_id, relation, strength),
        source_role=role,
        source_cluster_id=cluster,
    )


def test_authority_rank_follows_the_single_canonical_order() -> None:
    assert [authority_rank(role) for role in _ROLES] == [0, 1, 2, 3, 4]
    assert authority_rank("not_a_role") == len(_ROLES)


def test_support_only_is_not_a_conflict() -> None:
    state = _state(
        evidence=(_evidence("ev1"),),
        links=(_link("ev1", relation="supports", role="primary", cluster="c1"),),
    )

    result = assess_claim_conflict(state, state.claims[0])

    assert result.status == "none"
    assert result.has_conflict is False
    assert result.preferred_side == ""
    assert REASON_NO_CONFLICT in result.reasons


def test_tied_authority_stays_unresolved() -> None:
    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _link("ev1", relation="supports", role="authoritative_secondary", cluster="c1"),
            _link("ev2", relation="contradicts", role="authoritative_secondary", cluster="c2"),
        ),
    )

    result = assess_claim_conflict(state, state.claims[0])

    assert result.status == "unresolved_conflict"
    assert result.preferred_side == ""
    assert REASON_TIED_AUTHORITY in result.reasons
    assert REASON_COUNT_NOT_USED in result.reasons


def test_strict_authority_gap_prefers_the_stronger_side() -> None:
    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _link("ev1", relation="supports", role="primary", cluster="c1"),
            _link("ev2", relation="contradicts", role="community", cluster="c2"),
        ),
    )

    result = assess_claim_conflict(state, state.claims[0])

    assert result.status == "preferred_side"
    assert result.resolved is True
    assert result.preferred_side == "support"
    assert result.preferred_evidence_ids == ("ev1",)


def test_mirrored_conflict_prefers_the_other_side() -> None:
    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _link("ev1", relation="supports", role="community", cluster="c1"),
            _link("ev2", relation="contradicts", role="primary", cluster="c2"),
        ),
    )

    result = assess_claim_conflict(state, state.claims[0])

    assert result.status == "preferred_side"
    assert result.preferred_side == "contradict"
    assert result.preferred_evidence_ids == ("ev2",)


def test_two_primaries_on_opposite_sides_leave_the_conflict_unresolved() -> None:
    # Rank 0 is the strongest, so a side holding a primary can never be the
    # weaker side: two primaries tie and no preference may be formed.
    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2"), _evidence("ev3")),
        links=(
            _link("ev1", relation="supports", role="primary", cluster="c1"),
            _link("ev3", relation="supports", role="community", cluster="c3"),
            _link("ev2", relation="contradicts", role="primary", cluster="c2"),
        ),
    )

    result = assess_claim_conflict(state, state.claims[0])

    assert result.status == "unresolved_conflict"
    assert result.preferred_side == ""
    assert REASON_TIED_AUTHORITY in result.reasons


def test_source_count_never_decides() -> None:
    # Three weak sources must not outrank one strong source.
    three_weak_support = _state(
        evidence=(_evidence("s1"), _evidence("s2"), _evidence("s3"), _evidence("c1")),
        links=(
            _link("s1", relation="supports", role="community", cluster="k1"),
            _link("s2", relation="supports", role="community", cluster="k2"),
            _link("s3", relation="supports", role="community", cluster="k3"),
            _link("c1", relation="contradicts", role="primary", cluster="k4"),
        ),
    )
    result = assess_claim_conflict(three_weak_support, three_weak_support.claims[0])
    assert result.preferred_side == "contradict"

    # ...and the mirror must not flip the verdict to the numerous side.
    three_weak_contradict = _state(
        evidence=(_evidence("s1"), _evidence("c1"), _evidence("c2"), _evidence("c3")),
        links=(
            _link("s1", relation="supports", role="primary", cluster="k1"),
            _link("c1", relation="contradicts", role="community", cluster="k2"),
            _link("c2", relation="contradicts", role="community", cluster="k3"),
            _link("c3", relation="contradicts", role="community", cluster="k4"),
        ),
    )
    mirror = assess_claim_conflict(three_weak_contradict, three_weak_contradict.claims[0])
    assert mirror.preferred_side == "support"
    assert REASON_COUNT_NOT_USED in mirror.reasons


def test_stale_contradiction_is_filtered_by_eligibility_not_re_judged() -> None:
    # Freshness has exactly one truth (link eligibility); a stale link never
    # forms a side, so RQ-C reports no conflict rather than a stale one.
    state = _state(
        requirement=_requirement(max_age_days=30),
        reference_date="2026-09-14",
        evidence=(_evidence("ev1"), _evidence("ev2", published_at="2020-01-01")),
        links=(
            _link("ev1", relation="supports", role="primary", cluster="c1"),
            _link("ev2", relation="contradicts", role="primary", cluster="c2"),
        ),
    )

    result = assess_claim_conflict(state, state.claims[0])

    assert result.status == "none"
    assert result.contradicting == ()


def test_assessment_is_pure_and_reports_standings() -> None:
    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _link("ev1", relation="supports", role="primary", cluster="c1"),
            _link("ev2", relation="contradicts", role="community", cluster="c2"),
        ),
    )
    before = state.to_dict()

    result = assess_claim_conflict(state, state.claims[0])

    assert state.to_dict() == before
    assert result.supporting[0].authority_rank == 0
    assert result.supporting[0].direct is True
    assert result.supporting[0].fresh is True
    assert result.contradicting[0].authority_rank == 3
    assert set(result.to_dict()) >= {"status", "preferred_side", "reasons"}


def test_assess_state_conflicts_covers_every_claim() -> None:
    state = _state()

    results = assess_state_conflicts(state)

    assert len(results) == len(state.claims)
    assert results[0].claim_id == "claim1"


def test_safe_wrapper_returns_empty_when_assessor_fails(monkeypatch) -> None:
    state = _state()

    def boom(_state: ResearchState):
        raise RuntimeError("corrupt shadow projection")

    monkeypatch.setattr(
        "src.web.research.claim_conflict_assessment.assess_claim_conflict", boom
    )

    assert safe_assess_state_conflicts(state) == ()


def test_shadow_stop_exposes_conflicts_without_changing_decisions() -> None:
    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _link("ev1", relation="supports", role="primary", cluster="c1"),
            _link("ev2", relation="contradicts", role="community", cluster="c2"),
        ),
    )
    gate = evaluate_evidence_gate(state)

    result = evaluate_shadow_stop(state, legacy_would_stop=True)

    assert result.shadow_status == gate.status
    assert result.shadow_would_pass is (gate.status in {"pass", "partial"})
    assert result.shadow_would_block is (gate.status == "block")
    assert result.legacy_should_stop is True
    assert result.gate_result is not None
    assert result.gate_result.to_dict() == gate.to_dict()
    assert len(result.claim_conflicts) == 1
    assert result.claim_conflicts[0].preferred_side == "support"
    assert "claim_conflicts" in result.to_dict()
