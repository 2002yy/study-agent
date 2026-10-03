"""§144.11 Multimodal Reader v1: visual evidence flows through the existing RQ chain.

Contract proof, no new production code: a visual ``EvidenceUnit`` satisfies a
``modality="visual"`` requirement, participates in conflict, and drives the
coverage assessment -- i.e. there is no second, visual-only adequacy logic.
"""

from __future__ import annotations

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.claim_conflict_assessment import assess_claim_conflict
from src.web.research.claim_evidence_assessment import assess_claim_evidence
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
from src.web.research.coverage_stop_assessment import assess_coverage_stop
from src.web.research.evidence_units import (
    EvidenceUnit,
    RequiredUnit,
    unit_satisfies_modality,
)

_ROLES = ("primary", "authoritative_secondary", "independent_secondary", "community")


def _figure_unit(unit_id: str = "fig4", *, source_type: str = "chart") -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        source_type=source_type,  # type: ignore[arg-type]
        source="report.pdf",
        page=4,
        region="bbox:10,10,200,120",
        observation="Figure 4 shows feature X is unsupported on Windows.",
        provenance="report.pdf#page=4",
    )


def _requirement(*units: RequiredUnit) -> EvidenceRequirement:
    return EvidenceRequirement(
        source_roles=_ROLES,
        min_independent_sources=1,
        requires_primary_source=False,
        requires_successful_read=True,
        required_units=units,
    )


def _state(
    *,
    requirement: EvidenceRequirement,
    evidence: tuple[ResearchEvidence, ...],
    links: tuple[ResearchClaimEvidenceLink, ...],
) -> ResearchState:
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported on Windows?", "critical")],
        claims=[
            ResearchClaim(
                "c1",
                "q1",
                "Feature X is unsupported on Windows.",
                "factual",
                "critical",
                "searching",
                requirement,
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
        known_evidence_ids=tuple(item.evidence_id for item in evidence),
    )


def _link(
    evidence_id: str, *, relation: str = "supports", role: str = "primary"
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("c1", evidence_id, relation, 0.9),
        source_role=role,
        source_cluster_id=f"k:{evidence_id}",
    )


def test_visual_unit_round_trips_with_its_provenance() -> None:
    unit = _figure_unit()

    restored = EvidenceUnit.from_dict(unit.to_dict())

    assert restored == unit
    assert restored.is_visual is True
    assert restored.page == 4
    assert restored.region == "bbox:10,10,200,120"
    assert restored.provenance == "report.pdf#page=4"


def test_visual_requirement_is_covered_by_a_visual_unit() -> None:
    requirement = _requirement(RequiredUnit("fig4", "figure 4 conclusion", "visual"))
    state = _state(
        requirement=requirement,
        evidence=(
            ResearchEvidence(
                "ev1",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_figure_unit(),),
            ),
        ),
        links=(_link("ev1"),),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.semantic_adequacy == "adequate"
    assert result.state == "satisfied"
    assert result.missing_units == ()


def test_visual_requirement_is_not_covered_by_a_text_unit_with_the_same_id() -> None:
    requirement = _requirement(RequiredUnit("fig4", "figure 4 conclusion", "visual"))
    state = _state(
        requirement=requirement,
        evidence=(
            ResearchEvidence(
                "ev1",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(EvidenceUnit("fig4", "text"),),
            ),
        ),
        links=(_link("ev1"),),
    )

    result = assess_claim_evidence(state, state.claims[0])

    assert result.semantic_adequacy == "insufficient"
    assert result.state == "partially_satisfied"
    assert [unit.unit_id for unit in result.missing_units] == ["fig4"]
    assert unit_satisfies_modality(source_type="text", modality="visual") is False


def test_visual_evidence_participates_in_conflict_without_a_second_rule() -> None:
    state = _state(
        requirement=_requirement(RequiredUnit("fig4", "figure 4 conclusion", "visual")),
        evidence=(
            ResearchEvidence(
                "ev_fig",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_figure_unit(),),
            ),
            ResearchEvidence(
                "ev_text",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(EvidenceUnit("fig4", "text"),),
            ),
        ),
        links=(
            _link("ev_fig", role="primary"),
            _link("ev_text", relation="contradicts", role="community"),
        ),
    )

    conflict = assess_claim_conflict(state, state.claims[0])

    assert conflict.status == "preferred_side"
    assert conflict.preferred_side == "support"
    assert conflict.preferred_evidence_ids == ("ev_fig",)
    assert conflict.supporting[0].direct is True


def test_visual_adequacy_drives_the_coverage_assessment() -> None:
    requirement = _requirement(RequiredUnit("fig4", "figure 4 conclusion", "visual"))
    covered = _state(
        requirement=requirement,
        evidence=(
            ResearchEvidence(
                "ev1",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_figure_unit(),),
            ),
        ),
        links=(_link("ev1"),),
    )
    assert assess_coverage_stop(covered).recommendation == "stop_candidate"

    uncovered = _state(
        requirement=requirement,
        evidence=(
            ResearchEvidence(
                "ev1",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(EvidenceUnit("fig4", "text"),),
            ),
        ),
        links=(_link("ev1"),),
    )
    uncovered_result = assess_coverage_stop(uncovered)
    assert uncovered_result.recommendation == "continue_candidate"
    assert uncovered_result.blocking_claims[0].missing_unit_count == 1


def test_pdf_figure_and_screenshot_are_both_visual_source_types() -> None:
    for source_type in ("pdf_figure", "screenshot", "image", "chart"):
        assert unit_satisfies_modality(source_type=source_type, modality="visual") is True
        assert unit_satisfies_modality(source_type=source_type, modality="text") is False
