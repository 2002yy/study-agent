from __future__ import annotations

from src.domain.evidence import ClaimEvidenceLinkV1, EvidenceLifecycleStatus
from src.web.research.claim_evidence_assessment import (
    REASON_CONFLICTING_EVIDENCE,
    REASON_NO_ELIGIBLE_SUPPORT,
    REASON_NO_REQUIRED_UNITS,
    REASON_PRIMARY_SOURCE_MISSING,
    REASON_REQUIRED_UNITS_MET,
    REASON_REQUIRED_UNITS_MISSING,
    REASON_STRUCTURE_MET,
    assess_claim_evidence,
    assess_research_state,
    safe_assess_research_state,
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
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit
from src.web.research.stop_gate import evaluate_shadow_stop

_SOURCE_ROLES = ("primary", "authoritative_secondary", "independent_secondary")


def _requirement(
    *,
    required_units: tuple[RequiredUnit, ...] = (),
    min_sources: int = 2,
    requires_primary: bool = False,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        source_roles=_SOURCE_ROLES,
        min_independent_sources=min_sources,
        requires_primary_source=requires_primary,
        requires_successful_read=True,
        required_units=required_units,
    )


def _state(
    *,
    requirement: EvidenceRequirement,
    evidence: tuple[ResearchEvidence, ...] = (),
    links: tuple[ResearchClaimEvidenceLink, ...] = (),
    clusters: tuple[EvidenceCluster, ...] = (),
) -> ResearchState:
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "What is verified?", "critical")],
        claims=[
            ResearchClaim(
                "claim1",
                "q1",
                "A critical factual claim.",
                "factual",
                "critical",
                "searching",
                requirement,
            )
        ],
        evidence=evidence,
        evidence_links=links,
        source_clusters=clusters,
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            20, 8, 45, 60, 16000, candidates_used=2, reads_used=2, elapsed_seconds=10
        ),
        known_evidence_ids={item.evidence_id for item in evidence},
    )


def _support(
    evidence_id: str,
    *,
    cluster: str,
    role: str = "authoritative_secondary",
    strength: float = 0.9,
    relation: str = "supports",
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("claim1", evidence_id, relation, strength),
        source_role=role,
        source_cluster_id=cluster,
    )


def _evidence(
    evidence_id: str,
    *,
    units: tuple[EvidenceUnit, ...] = (),
    lifecycle: EvidenceLifecycleStatus = "read",
) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id,
        lifecycle_status=lifecycle,
        extraction_status="eligible",
        units=units,
    )


def test_empty_required_units_is_not_evaluated() -> None:
    state = _state(
        requirement=_requirement(),
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.semantic_adequacy == "not_evaluated"
    assert result.semantic_coverage is None
    assert result.state == "satisfied"
    assert result.structural_coverage == 1.0
    assert REASON_NO_REQUIRED_UNITS in result.reasons


def test_structure_and_units_met_is_satisfied() -> None:
    required = (RequiredUnit("u1", "feature X", "text"),)
    state = _state(
        requirement=_requirement(required_units=required),
        evidence=(
            _evidence("ev1", units=(EvidenceUnit("u1", "text"),)),
            _evidence("ev2"),
        ),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.state == "satisfied"
    assert result.semantic_adequacy == "adequate"
    assert result.missing_units == ()
    assert result.covered_units == required
    assert result.semantic_coverage == 1.0
    assert REASON_STRUCTURE_MET in result.reasons
    assert REASON_REQUIRED_UNITS_MET in result.reasons


def test_structure_met_but_units_missing_is_partial_insufficient() -> None:
    # The §143-C gap: shape is adequate, but the content unit was never read.
    required = (RequiredUnit("u1", "feature X", "text"),)
    state = _state(
        requirement=_requirement(required_units=required),
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.state == "partially_satisfied"
    assert result.semantic_adequacy == "insufficient"
    assert result.missing_units == required
    assert result.semantic_coverage == 0.0
    assert REASON_REQUIRED_UNITS_MISSING in result.reasons


def test_partially_covered_units_is_partial_adequacy() -> None:
    required = (
        RequiredUnit("u1", "feature X", "text"),
        RequiredUnit("u2", "feature Y", "text"),
    )
    state = _state(
        requirement=_requirement(required_units=required),
        evidence=(
            _evidence("ev1", units=(EvidenceUnit("u1", "text"),)),
            _evidence("ev2"),
        ),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.state == "partially_satisfied"
    assert result.semantic_adequacy == "partial"
    assert result.covered_units == (RequiredUnit("u1", "feature X", "text"),)
    assert result.missing_units == (RequiredUnit("u2", "feature Y", "text"),)
    assert result.semantic_coverage == 0.5


def test_visual_requirement_is_not_covered_by_text_unit() -> None:
    required = (RequiredUnit("u1", "figure 4 conclusion", "visual"),)
    state = _state(
        requirement=_requirement(required_units=required),
        evidence=(
            _evidence("ev1", units=(EvidenceUnit("u1", "text"),)),
            _evidence("ev2"),
        ),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.missing_units == required
    assert result.semantic_adequacy == "insufficient"


def test_visual_requirement_is_covered_by_visual_unit() -> None:
    required = (RequiredUnit("u1", "figure 4 conclusion", "visual"),)
    state = _state(
        requirement=_requirement(required_units=required),
        evidence=(
            _evidence(
                "ev1",
                units=(
                    EvidenceUnit(
                        "u1",
                        "pdf_figure",
                        page=4,
                        region="bbox:1",
                        observation="feature X is unsupported",
                        provenance="doc.pdf#page=4",
                    ),
                ),
            ),
            _evidence("ev2"),
        ),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.missing_units == ()
    assert result.semantic_adequacy == "adequate"
    assert result.state == "satisfied"


def test_conflict_with_support_is_contested() -> None:
    state = _state(
        requirement=_requirement(),
        evidence=(_evidence("ev1"), _evidence("ev2"), _evidence("ev3")),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
            _support("ev3", cluster="c3", relation="contradicts"),
        ),
        clusters=(
            EvidenceCluster("c1", ("ev1",)),
            EvidenceCluster("c2", ("ev2",)),
            EvidenceCluster("c3", ("ev3",)),
        ),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.state == "contested"
    assert result.conflict_flag is True
    assert result.contradicting_clusters == 1
    assert REASON_CONFLICTING_EVIDENCE in result.reasons


def test_no_eligible_support_is_unresolved() -> None:
    state = _state(
        requirement=_requirement(required_units=(RequiredUnit("u1"),)),
        evidence=(),
        links=(),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.state == "unresolved"
    assert result.semantic_adequacy == "insufficient"
    assert result.supporting_clusters == 0
    assert REASON_NO_ELIGIBLE_SUPPORT in result.reasons


def test_weak_links_below_threshold_are_ignored() -> None:
    state = _state(
        requirement=_requirement(min_sources=1),
        evidence=(_evidence("ev1"),),
        links=(_support("ev1", cluster="c1", strength=0.5),),
        clusters=(EvidenceCluster("c1", ("ev1",)),),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.supporting_clusters == 0
    assert result.state == "unresolved"


def test_primary_requirement_shortfall_is_structure_short() -> None:
    state = _state(
        requirement=_requirement(min_sources=1, requires_primary=True),
        evidence=(_evidence("ev1"),),
        links=(_support("ev1", cluster="c1"),),
        clusters=(EvidenceCluster("c1", ("ev1",)),),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.has_primary is False
    assert result.state == "partially_satisfied"
    assert REASON_PRIMARY_SOURCE_MISSING in result.reasons


def test_assessment_is_pure_and_does_not_mutate_state() -> None:
    state = _state(
        requirement=_requirement(required_units=(RequiredUnit("u1"),)),
        evidence=(_evidence("ev1", units=(EvidenceUnit("u1", "text"),)), _evidence("ev2")),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )
    before = state.to_dict()

    assess_claim_evidence(state, state.claims[0])

    assert state.to_dict() == before


def test_assess_research_state_covers_every_claim() -> None:
    state = _state(requirement=_requirement(min_sources=0), evidence=(), links=())

    assessments = assess_research_state(state)

    assert len(assessments) == len(state.claims)
    assert assessments[0].claim_id == "claim1"


def test_safe_assessment_returns_empty_when_assessor_fails(monkeypatch) -> None:
    state = _state(requirement=_requirement(min_sources=0), evidence=(), links=())

    def boom(_state: ResearchState):
        raise RuntimeError("corrupt shadow projection")

    monkeypatch.setattr(
        "src.web.research.claim_evidence_assessment.assess_claim_evidence", boom
    )

    assert safe_assess_research_state(state) == ()


def test_shadow_stop_exposes_assessments_without_changing_decisions() -> None:
    state = _state(
        requirement=_requirement(required_units=(RequiredUnit("u1", "feature X", "text"),)),
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _support("ev1", cluster="c1", role="primary"),
            _support("ev2", cluster="c2"),
        ),
        clusters=(EvidenceCluster("c1", ("ev1",)), EvidenceCluster("c2", ("ev2",))),
    )
    gate = evaluate_evidence_gate(state)

    result = evaluate_shadow_stop(state, legacy_would_stop=True)

    # Decision surface is untouched by RQ-A.
    assert result.shadow_status == gate.status
    assert result.shadow_would_pass is (gate.status in {"pass", "partial"})
    assert result.shadow_would_block is (gate.status == "block")
    assert result.legacy_should_stop is True
    assert result.open_critical_claims == gate.open_critical_claims
    assert result.gate_result is not None
    assert result.gate_result.to_dict() == gate.to_dict()
    # RQ-A observability is attached and reports the semantic gap.
    assert len(result.claim_assessments) == 1
    assert result.claim_assessments[0].semantic_adequacy == "insufficient"
    assert result.claim_assessments[0].missing_units == (
        RequiredUnit("u1", "feature X", "text"),
    )
    assert "claim_assessments" in result.to_dict()
