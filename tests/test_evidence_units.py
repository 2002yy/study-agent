from __future__ import annotations

import pytest

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.contracts import (
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    build_research_state,
)
from src.web.research.evidence_units import (
    EvidenceUnit,
    RequiredUnit,
    parse_evidence_units,
    parse_required_units,
    unit_satisfies_modality,
)


@pytest.mark.parametrize(
    ("source_type", "modality", "expected"),
    [
        ("text", "text", True),
        ("table", "text", True),
        ("image", "text", False),
        ("text", "visual", False),
        ("table", "visual", False),
        ("image", "visual", True),
        ("chart", "visual", True),
        ("screenshot", "visual", True),
        ("pdf_figure", "visual", True),
        ("text", "any", True),
        ("pdf_figure", "any", True),
    ],
)
def test_unit_satisfies_modality_table(
    source_type: str, modality: str, expected: bool
) -> None:
    assert (
        unit_satisfies_modality(source_type=source_type, modality=modality) is expected
    )


def test_visual_requirement_cannot_be_met_by_text_evidence() -> None:
    # The exact §144.4 invariant: "prose mentions a figure" != "figure was read".
    assert unit_satisfies_modality(source_type="text", modality="visual") is False


def test_evidence_unit_round_trip() -> None:
    unit = EvidenceUnit(
        unit_id="u1",
        source_type="pdf_figure",
        source="doc.pdf",
        page=4,
        region="bbox:10,10,200,120",
        observation="Figure 4 shows feature X is unsupported.",
        contradicts=("claim1",),
        confidence=0.8,
        provenance="doc.pdf#page=4",
    )
    restored = EvidenceUnit.from_dict(unit.to_dict())
    assert restored == unit
    assert restored.is_visual is True


def test_required_unit_round_trip() -> None:
    unit = RequiredUnit(unit_id="u1", description="feature X support", modality="visual")
    assert RequiredUnit.from_dict(unit.to_dict()) == unit


def test_parse_rejects_unknown_keys_and_bad_values() -> None:
    with pytest.raises(ValueError):
        parse_required_units([{"unit_id": "u1", "bogus": 1}])
    with pytest.raises(ValueError):
        parse_required_units([{"unit_id": "u1", "modality": "audio"}])
    with pytest.raises(ValueError):
        parse_evidence_units([{"unit_id": "u1", "source_type": "video"}])
    with pytest.raises(ValueError):
        parse_evidence_units([{"unit_id": "u1", "confidence": 1.5}])
    with pytest.raises(ValueError):
        parse_evidence_units([{"unit_id": ""}])


def test_empty_units_are_omitted_and_accepted() -> None:
    assert parse_required_units(None) == ()
    assert parse_evidence_units(None) == ()
    assert parse_required_units([]) == ()


def test_research_state_round_trip_preserves_units() -> None:
    requirement = EvidenceRequirement(
        source_roles=("authoritative_secondary",),
        min_independent_sources=1,
        required_units=(RequiredUnit("u1", "feature X", "visual"),),
    )
    evidence = ResearchEvidence(
        "ev1",
        lifecycle_status="read",
        extraction_status="eligible",
        units=(EvidenceUnit("u1", "chart", region="bbox:1", provenance="p#1"),),
    )
    state = build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "What is verified?", "critical")],
        claims=[
            ResearchClaim("claim1", "q1", "A claim.", "factual", "critical", "searching", requirement)
        ],
        evidence=(evidence,),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000, candidates_used=1, reads_used=1, elapsed_seconds=1),
        known_evidence_ids=("ev1",),
    )
    restored = type(state).from_dict(state.to_dict(), known_evidence_ids=("ev1",))
    assert restored.claims[0].evidence_requirement.required_units == (
        RequiredUnit("u1", "feature X", "visual"),
    )
    assert restored.evidence[0].units == (
        EvidenceUnit("u1", "chart", region="bbox:1", provenance="p#1"),
    )


def test_legacy_state_without_units_still_parses() -> None:
    # Backward compatibility: old persisted payloads have no unit keys.
    requirement = EvidenceRequirement(source_roles=("authoritative_secondary",))
    state = build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Q?", "critical")],
        claims=[
            ResearchClaim("claim1", "q1", "A claim.", "factual", "critical", "searching", requirement)
        ],
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000, candidates_used=0, reads_used=0, elapsed_seconds=0),
        known_evidence_ids=(),
    )
    payload = state.to_dict()
    for claim in payload["claims"]:
        claim["evidence_requirement"].pop("required_units")
    restored = type(state).from_dict(payload, known_evidence_ids=())
    assert restored.claims[0].evidence_requirement.required_units == ()


def test_link_helper_is_not_bypassed() -> None:
    # Sanity: the domain link value is what carries relation/strength.
    link = ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("claim1", "ev1", "supports", 0.9),
        source_role="authoritative_secondary",
        source_cluster_id="c1",
    )
    assert link.relation == "supports"
    assert link.strength == 0.9
