"""§144 RQ-D: coverage-aware stop assessment (advisory, judgement only)."""

from __future__ import annotations

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchClaimPriority,
    ResearchEvidence,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.coverage_stop_assessment import (
    REASON_ALL_CRITICAL_COVERED,
    REASON_CONFLICT_UNRESOLVED,
    REASON_NO_CRITICAL_CLAIMS,
    REASON_NO_REQUIREMENT,
    REASON_SEMANTIC_GAP,
    REASON_VOLUME_NOT_USED,
    assess_coverage_stop,
    safe_assess_coverage_stop,
)
from src.web.research.evidence_gate import evaluate_evidence_gate
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit
from src.web.research.stop_gate import evaluate_shadow_stop

_ROLES = ("primary", "authoritative_secondary", "independent_secondary", "community")


def _requirement(*required_units: str) -> EvidenceRequirement:
    return EvidenceRequirement(
        source_roles=_ROLES,
        min_independent_sources=1,
        requires_primary_source=False,
        requires_successful_read=True,
        required_units=tuple(RequiredUnit(unit_id=unit) for unit in required_units),
    )


def _evidence(evidence_id: str, *units: str) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id,
        lifecycle_status="read",
        extraction_status="eligible",
        units=tuple(EvidenceUnit(unit_id=unit) for unit in units),
    )


def _link(
    claim_id: str,
    evidence_id: str,
    *,
    relation: str = "supports",
    role: str = "primary",
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1(claim_id, evidence_id, relation, 0.9),
        source_role=role,
        source_cluster_id=f"{claim_id}:{evidence_id}",
    )


def _state(
    *,
    claims: list[tuple[str, ResearchClaimPriority, tuple[str, ...]]],
    evidence: tuple[ResearchEvidence, ...] = (),
    links: tuple[ResearchClaimEvidenceLink, ...] = (),
) -> ResearchState:
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Which claims are covered?", "critical")],
        claims=[
            ResearchClaim(
                claim_id,
                "q1",
                f"claim {claim_id}",
                "factual",
                priority,
                "searching",
                _requirement(*required_units),
            )
            for claim_id, priority, required_units in claims
        ],
        evidence=evidence,
        evidence_links=links,
        source_clusters=tuple(
            EvidenceCluster(link.source_cluster_id, (link.evidence_id,)) for link in links
        ),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000),
        known_evidence_ids=tuple(item.evidence_id for item in evidence),
    )


def test_no_critical_claims_cannot_justify_a_coverage_stop() -> None:
    state = _state(claims=[("c1", "major", ("u1",))])

    result = assess_coverage_stop(state)

    assert result.critical_claim_count == 0
    assert result.recommendation == "continue_candidate"
    assert result.blocks_stop is False
    assert REASON_NO_CRITICAL_CLAIMS in result.reasons


def test_all_critical_claims_adequate_is_a_stop_candidate() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1",))],
        evidence=(_evidence("ev1", "u1"),),
        links=(_link("c1", "ev1"),),
    )

    result = assess_coverage_stop(state)

    assert result.status == "covered"
    assert result.recommendation == "stop_candidate"
    assert result.adequate_critical_claim_count == 1
    assert result.blocking_claims == ()
    assert REASON_ALL_CRITICAL_COVERED in result.reasons


def test_missing_required_units_blocks_a_coverage_stop() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1", "u2"))],
        evidence=(_evidence("ev1", "u1"),),
        links=(_link("c1", "ev1"),),
    )

    result = assess_coverage_stop(state)

    assert result.recommendation == "continue_candidate"
    assert result.status == "gaps_remain"
    assert result.blocks_stop is True
    assert [gap.claim_id for gap in result.blocking_claims] == ["c1"]
    assert result.blocking_claims[0].missing_unit_count == 1
    assert result.blocking_claims[0].semantic_adequacy == "partial"
    assert REASON_SEMANTIC_GAP in result.reasons


def test_unresolved_critical_conflict_blocks_even_when_adequate() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1",))],
        evidence=(_evidence("ev1", "u1"), _evidence("ev2", "u1")),
        links=(
            _link("c1", "ev1", role="authoritative_secondary"),
            _link("c1", "ev2", relation="contradicts", role="authoritative_secondary"),
        ),
    )

    result = assess_coverage_stop(state)

    assert result.recommendation == "continue_candidate"
    assert result.status == "conflict_unresolved"
    assert result.unresolved_conflict_claim_ids == ("c1",)
    assert result.adequate_critical_claim_count == 1
    assert REASON_CONFLICT_UNRESOLVED in result.reasons


def test_resolved_critical_conflict_does_not_block() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1",))],
        evidence=(_evidence("ev1", "u1"), _evidence("ev2", "u1")),
        links=(
            _link("c1", "ev1", role="primary"),
            _link("c1", "ev2", relation="contradicts", role="community"),
        ),
    )

    result = assess_coverage_stop(state)

    assert result.recommendation == "stop_candidate"
    assert result.unresolved_conflict_claim_ids == ()


def test_claim_without_required_units_is_recorded_but_not_blocking() -> None:
    # Nothing was declared, so coverage cannot demand units that were never asked for.
    state = _state(
        claims=[("c1", "critical", ())],
        evidence=(_evidence("ev1", "anything"),),
        links=(_link("c1", "ev1"),),
    )

    result = assess_coverage_stop(state)

    assert result.recommendation == "stop_candidate"
    assert result.blocking_claims == ()
    assert REASON_NO_REQUIREMENT in result.reasons


def test_non_critical_claims_do_not_block() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1",)), ("c2", "major", ("u9",))],
        evidence=(_evidence("ev1", "u1"),),
        links=(_link("c1", "ev1"), _link("c2", "ev1")),
    )

    result = assess_coverage_stop(state)

    assert result.critical_claim_count == 1
    assert result.recommendation == "stop_candidate"


def test_evidence_volume_is_reported_but_never_decides() -> None:
    # Many sources, still short one unit -> must not become a stop candidate.
    many = _state(
        claims=[("c1", "critical", ("u1", "u2"))],
        evidence=tuple(_evidence(f"ev{i}", "u1") for i in range(1, 6)),
        links=tuple(_link("c1", f"ev{i}") for i in range(1, 6)),
    )
    many_result = assess_coverage_stop(many)
    assert many_result.evidence_count == 5
    assert many_result.recommendation == "continue_candidate"

    # One source, fully covering -> a stop candidate, despite the smaller volume.
    few = _state(
        claims=[("c1", "critical", ("u1",))],
        evidence=(_evidence("ev1", "u1"),),
        links=(_link("c1", "ev1"),),
    )
    few_result = assess_coverage_stop(few)
    assert few_result.evidence_count == 1
    assert few_result.recommendation == "stop_candidate"
    assert REASON_VOLUME_NOT_USED in few_result.reasons


def test_assessment_is_pure() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1",))],
        evidence=(_evidence("ev1", "u1"),),
        links=(_link("c1", "ev1"),),
    )
    before = state.to_dict()

    assess_coverage_stop(state)

    assert state.to_dict() == before


def test_safe_wrapper_returns_none_when_assessor_fails(monkeypatch) -> None:
    state = _state(claims=[("c1", "critical", ("u1",))])

    def boom(_state: ResearchState):
        raise RuntimeError("corrupt shadow projection")

    monkeypatch.setattr(
        "src.web.research.coverage_stop_assessment.assess_coverage_stop", boom
    )

    assert safe_assess_coverage_stop(state) is None


def test_shadow_stop_exposes_coverage_without_changing_decisions() -> None:
    state = _state(
        claims=[("c1", "critical", ("u1",))],
        evidence=(_evidence("ev1", "u1"),),
        links=(_link("c1", "ev1"),),
    )
    gate = evaluate_evidence_gate(state)

    result = evaluate_shadow_stop(state, legacy_would_stop=True)

    assert result.shadow_status == gate.status
    assert result.shadow_would_pass is (gate.status in {"pass", "partial"})
    assert result.legacy_should_stop is True
    assert result.gate_result is not None
    assert result.gate_result.to_dict() == gate.to_dict()
    assert result.coverage_assessment is not None
    assert result.coverage_assessment.recommendation == "stop_candidate"
    assert "coverage_assessment" in result.to_dict()
