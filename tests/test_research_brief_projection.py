"""§147 ResearchBrief projection: authority, principles, deterministic confidence."""

from __future__ import annotations

import pytest

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.claim_conflict_assessment import assess_claim_conflict
from src.web.research.claim_evidence_assessment import assess_claim_evidence
from src.web.research.contracts import (
    EvidenceCluster,
    ResearchBrief,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit
from src.web.research.research_brief_projection import (
    LIMITATION_BUDGET_EXHAUSTED,
    LIMITATION_CRITICAL_NOT_SATISFIED,
    LIMITATION_NO_REQUIRED_UNITS,
    LIMITATION_PRIMARY_SOURCE_MISSING,
    LIMITATION_UNRESOLVED_CONFLICTS,
    MODALITY_UNKNOWN,
    REASON_REQUIRED_UNITS_MISSING,
    REASON_UNRESOLVED_CONFLICT,
    brief_confidence,
    build_research_brief_projection,
    safe_build_research_brief_projection,
)

_ROLES = ("primary", "authoritative_secondary", "community")


def _requirement(
    *required_units: str,
    min_sources: int = 1,
    requires_primary: bool = False,
) -> EvidenceRequirement:
    return EvidenceRequirement(
        source_roles=_ROLES,
        min_independent_sources=min_sources,
        requires_primary_source=requires_primary,
        requires_successful_read=True,
        required_units=tuple(
            RequiredUnit(unit_id=unit, modality="any") for unit in required_units
        ),
    )


def _evidence(evidence_id: str, *units: EvidenceUnit) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id,
        lifecycle_status="read",
        extraction_status="eligible",
        units=units,
    )


def _link(
    evidence_id: str,
    *,
    relation: str = "supports",
    role: str = "primary",
    cluster: str = "",
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("c1", evidence_id, relation, 0.9),
        source_role=role,
        source_cluster_id=cluster or f"k_{evidence_id}",
    )


def _state(
    *,
    requirement: EvidenceRequirement | None = None,
    evidence: tuple[ResearchEvidence, ...] = (),
    links: tuple[ResearchClaimEvidenceLink, ...] = (),
    priority: str = "critical",
    elapsed: float = 1.0,
    brief: ResearchBrief | None = None,
) -> ResearchState:
    return build_research_state(
        brief=brief,
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported?", "critical")],
        claims=[
            ResearchClaim(
                "c1",
                "q1",
                "Feature X is unsupported.",
                "factual",
                priority,  # type: ignore[arg-type]
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
        budget=ResearchBudget(20, 8, 45, 60, 16000, elapsed_seconds=elapsed),
        known_evidence_ids=tuple(item.evidence_id for item in evidence),
    )


def _text_unit(unit_id: str = "u1") -> EvidenceUnit:
    return EvidenceUnit(unit_id=unit_id, source_type="text")


def _chart_unit(unit_id: str = "fig4") -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        source_type="chart",
        source="https://cdn.example.com/f4.png",
        page=4,
        region="bbox:1",
        provenance="https://cdn.example.com/f4.png#page=4",
    )


# ------------------------------------------------------------------ confidence

@pytest.mark.parametrize(
    ("adequacy_state", "conflict_status", "expected"),
    [
        ("not_evaluated", "none", "not_evaluated"),
        ("insufficient", "none", "low"),
        ("adequate", "unresolved_conflict", "unresolved"),
        ("partial", "none", "medium"),
        ("adequate", "none", "high"),
        ("adequate", "preferred_side", "high"),
    ],
)
def test_confidence_mapping_table(adequacy_state: str, conflict_status: str, expected: str) -> None:
    class _Assessment:
        semantic_adequacy = adequacy_state
        supporting_clusters = 2
        required_clusters = 1
        has_primary = True

    assert brief_confidence(_Assessment(), conflict_status=conflict_status) == expected  # type: ignore[arg-type]


def test_confidence_is_medium_when_structure_is_short_of_the_requirement() -> None:
    class _Assessment:
        semantic_adequacy = "adequate"
        supporting_clusters = 1
        required_clusters = 2
        has_primary = True

    assert brief_confidence(_Assessment(), conflict_status="none") == "medium"  # type: ignore[arg-type]


def test_confidence_is_medium_when_a_required_primary_is_missing() -> None:
    class _Assessment:
        semantic_adequacy = "adequate"
        supporting_clusters = 1
        required_clusters = 1
        has_primary = False

    assert brief_confidence(_Assessment(), conflict_status="none") == "medium"  # type: ignore[arg-type]


def test_confidence_never_returns_a_float() -> None:
    state = _state(
        requirement=_requirement("u1"),
        evidence=(_evidence("ev1", _text_unit()),),
        links=(_link("ev1"),),
    )

    brief = build_research_brief_projection(state)

    assert isinstance(brief.claims[0].confidence, str)
    assert brief.claims[0].confidence in {"not_evaluated", "unresolved", "low", "medium", "high"}


# ------------------------------------------------------------------- principles

def test_p1_values_are_copied_from_the_assessors_not_re_judged() -> None:
    state = _state(
        requirement=_requirement("u1", "u2"),
        evidence=(_evidence("ev1", _text_unit("u1")),),
        links=(_link("ev1"),),
    )

    brief = build_research_brief_projection(state)
    evidence_view = assess_claim_evidence(state, state.claims[0])
    conflict_view = assess_claim_conflict(state, state.claims[0])

    claim = brief.claims[0]
    assert claim.semantic_adequacy == evidence_view.semantic_adequacy
    assert claim.status == evidence_view.state
    assert claim.evidence_refs == tuple(
        dict.fromkeys((*evidence_view.supporting_evidence, *evidence_view.contradicting_evidence))
    )
    assert brief.contradictions == () or brief.contradictions[0].conflict_status == conflict_view.status


def test_p2_not_evaluated_is_never_dressed_up() -> None:
    state = _state(
        requirement=_requirement(),
        evidence=(_evidence("ev1", _text_unit()),),
        links=(_link("ev1"),),
    )

    brief = build_research_brief_projection(state)

    assert brief.claims[0].semantic_adequacy == "not_evaluated"
    assert brief.claims[0].confidence == "not_evaluated"
    assert LIMITATION_NO_REQUIRED_UNITS in brief.limitations


def test_p3_preferred_side_never_deletes_the_other_side() -> None:
    state = _state(
        requirement=_requirement("u1"),
        evidence=(_evidence("ev_fig", _chart_unit("u1")), _evidence("ev_text")),
        links=(
            _link("ev_fig", role="primary"),
            _link("ev_text", relation="contradicts", role="community"),
        ),
    )

    brief = build_research_brief_projection(state)
    contradiction = brief.contradictions[0]

    assert contradiction.conflict_status == "preferred_side"
    assert contradiction.preferred_side == "support"
    assert contradiction.support_refs == ("ev_fig",)
    assert contradiction.contradict_refs == ("ev_text",)


def test_p4_missing_mirrors_the_frozen_requirement_only() -> None:
    state = _state(
        requirement=_requirement("u1", "u2"),
        evidence=(_evidence("ev1", _text_unit("u1")),),
        links=(_link("ev1"),),
    )

    brief = build_research_brief_projection(state)

    assert len(brief.missing) == 1
    assert brief.missing[0].reason == REASON_REQUIRED_UNITS_MISSING
    assert brief.missing[0].missing_required_units == ("u2",)


def test_p4_no_missing_entry_when_nothing_was_required_and_nothing_conflicts() -> None:
    state = _state(
        requirement=_requirement(),
        evidence=(_evidence("ev1", _text_unit()),),
        links=(_link("ev1"),),
    )

    brief = build_research_brief_projection(state)

    assert brief.missing == ()


def test_p4_unresolved_conflict_appears_as_a_missing_reason() -> None:
    state = _state(
        requirement=_requirement("u1"),
        evidence=(_evidence("ev1", _chart_unit("u1")), _evidence("ev2")),
        links=(
            _link("ev1", role="authoritative_secondary"),
            _link("ev2", relation="contradicts", role="authoritative_secondary"),
        ),
    )

    brief = build_research_brief_projection(state)

    assert [item.reason for item in brief.missing] == [REASON_UNRESOLVED_CONFLICT]
    assert LIMITATION_UNRESOLVED_CONFLICTS in brief.limitations


def test_p5_source_map_uses_one_model_for_text_and_visual() -> None:
    state = _state(
        requirement=_requirement("u1", "fig4"),
        evidence=(
            _evidence("ev_text", _text_unit("u1")),
            _evidence("ev_fig", _chart_unit("fig4")),
        ),
        links=(_link("ev_text"), _link("ev_fig", role="authoritative_secondary")),
    )

    brief = build_research_brief_projection(state)
    modalities = {item.evidence_id: item.modality for item in brief.source_map}

    assert modalities["ev_text"] == "text"
    assert modalities["ev_fig"] == "chart"
    visual = next(item for item in brief.source_map if item.evidence_id == "ev_fig")
    assert visual.provenance.startswith("https://cdn.example.com/f4.png")
    assert visual.locator == visual.provenance


def test_p5_evidence_without_units_reports_unknown_modality() -> None:
    state = _state(
        requirement=_requirement("u1"),
        evidence=(_evidence("ev1"),),
        links=(_link("ev1"),),
    )

    brief = build_research_brief_projection(state)

    assert brief.source_map[0].modality == MODALITY_UNKNOWN


def test_p7_missing_and_limitations_stay_separate() -> None:
    state = _state(
        requirement=_requirement("u1", "u2", requires_primary=True),
        evidence=(_evidence("ev1", _text_unit("u1")),),
        links=(_link("ev1", role="community"),),
    )

    brief = build_research_brief_projection(state)

    # claim-level gap
    assert [item.claim_id for item in brief.missing] == ["c1"]
    # run-level limitations
    assert LIMITATION_CRITICAL_NOT_SATISFIED in brief.limitations
    assert LIMITATION_PRIMARY_SOURCE_MISSING in brief.limitations
    assert all(item.reason not in brief.limitations for item in brief.missing)


def test_budget_exhaustion_is_a_run_level_limitation() -> None:
    state = _state(
        requirement=_requirement("u1"),
        evidence=(_evidence("ev1", _text_unit("u1")),),
        links=(_link("ev1"),),
        elapsed=60.0,
    )

    brief = build_research_brief_projection(state)

    assert LIMITATION_BUDGET_EXHAUSTED in brief.limitations


def test_non_critical_claims_do_not_raise_critical_limitations() -> None:
    state = _state(
        requirement=_requirement("u1", "u2"),
        evidence=(_evidence("ev1", _text_unit("u1")),),
        links=(_link("ev1"),),
        priority="context",
    )

    brief = build_research_brief_projection(state)

    assert LIMITATION_CRITICAL_NOT_SATISFIED not in brief.limitations
    assert [item.reason for item in brief.missing] == [REASON_REQUIRED_UNITS_MISSING]


# ------------------------------------------------------------- shape and safety

def test_projection_carries_the_question_and_is_pure() -> None:
    state = _state(requirement=_requirement("u1"), evidence=(), links=())
    before = state.to_dict()

    brief = build_research_brief_projection(state)

    assert brief.question is not None
    assert brief.question.question_id == "q1"
    assert state.to_dict() == before


def test_projection_is_not_part_of_the_persisted_state_schema() -> None:
    state = _state(
        requirement=_requirement("u1"),
        evidence=(),
        links=(),
        brief=ResearchBrief(claim_ids=("c1",), outline=("eligible_evidence",)),
    )

    payload = state.to_dict()
    brief = build_research_brief_projection(state).to_dict()

    # the persisted brief stays the gate-owned minimal summary
    assert set(payload["brief"]) == {
        "claim_ids",
        "unresolved_claim_ids",
        "conflict_gap_ids",
        "outline",
    }
    # the projection adds no persisted channel
    assert "source_map" not in payload
    assert "limitations" not in payload
    assert set(brief) == {
        "question",
        "claims",
        "contradictions",
        "missing",
        "source_map",
        "limitations",
    }


def test_safe_wrapper_returns_none_when_the_projection_fails(monkeypatch) -> None:
    state = _state(requirement=_requirement("u1"), evidence=(), links=())

    def boom(_state: ResearchState):
        raise RuntimeError("corrupt state")

    monkeypatch.setattr(
        "src.web.research.research_brief_projection.assess_claim_evidence", boom
    )

    assert safe_build_research_brief_projection(state) is None
