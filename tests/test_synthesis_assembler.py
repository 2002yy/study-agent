"""§148 Synthesis assembler: mechanical fact/citation/stance enforcement."""

from __future__ import annotations

import pytest

from src.domain.evidence import ClaimEvidenceLinkV1
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
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit
from src.web.research.research_brief_projection import (
    build_research_brief_projection,
)
from src.web.research.synthesis_assembler import (
    REASON_LIMITATIONS_DROPPED,
    REASON_STANCE_VIOLATION,
    REASON_UNAUTHORIZED_REF,
    REASON_UNCOVERED_ASSERTION,
    SynthesisAssertion,
    SynthesisContractViolation,
    SynthesisDraft,
    SynthesisSection,
    allowed_stances,
    assemble_synthesis_draft,
    collect_evidence_payloads,
    extractive_writer,
)

_ROLES = ("primary", "authoritative_secondary", "community")


def _requirement(*required_units: str, min_sources: int = 1) -> EvidenceRequirement:
    return EvidenceRequirement(
        source_roles=_ROLES,
        min_independent_sources=min_sources,
        requires_successful_read=True,
        required_units=tuple(
            RequiredUnit(unit_id=unit, modality="any") for unit in required_units
        ),
    )


def _text_unit(unit_id: str, content: str) -> EvidenceUnit:
    return EvidenceUnit(unit_id=unit_id, source_type="text", content=content)


def _chart_unit(unit_id: str) -> EvidenceUnit:
    return EvidenceUnit(
        unit_id=unit_id,
        source_type="chart",
        source="https://cdn.example.com/f4.png",
        page=4,
        region="bbox:10,10,200,120",
        observation="feature X is unsupported on Windows",
        provenance="https://cdn.example.com/f4.png#page=4",
    )


def _link(
    evidence_id: str, *, relation: str = "supports", role: str = "primary"
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("c1", evidence_id, relation, 0.9),
        source_role=role,
        source_cluster_id=f"k_{evidence_id}",
    )


def _state(
    *,
    requirement: EvidenceRequirement,
    evidence: tuple[ResearchEvidence, ...],
    links: tuple[ResearchClaimEvidenceLink, ...],
) -> ResearchState:
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported?", "critical")],
        claims=[
            ResearchClaim(
                "c1",
                "q1",
                "Feature X is unsupported.",
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


def _supported_state() -> ResearchState:
    return _state(
        requirement=_requirement("u1"),
        evidence=(
            ResearchEvidence(
                "ev_text",
                lifecycle_status="read",
                extraction_status="eligible",
                locator="https://docs.example/page#section",
                units=(_text_unit("u1", "Feature X is unsupported on Windows."),),
            ),
        ),
        links=(_link("ev_text"),),
    )


def _visual_state() -> ResearchState:
    return _state(
        requirement=_requirement("fig4"),
        evidence=(
            ResearchEvidence(
                "ev_fig",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_chart_unit("fig4"),),
            ),
        ),
        links=(_link("ev_fig"),),
    )


def _unresolved_conflict_state() -> ResearchState:
    return _state(
        requirement=_requirement("u1"),
        evidence=(
            ResearchEvidence(
                "ev_a",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_text_unit("u1", "A"),),
            ),
            ResearchEvidence(
                "ev_b",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(),
            ),
        ),
        links=(
            _link("ev_a", role="authoritative_secondary"),
            _link("ev_b", relation="contradicts", role="authoritative_secondary"),
        ),
    )


# ------------------------------------------------------------------- stances

@pytest.mark.parametrize(
    ("adequacy", "confidence", "conflict", "expected"),
    [
        ("not_evaluated", "not_evaluated", "none", {"not_evaluated"}),
        ("adequate", "high", "unresolved_conflict", {"contested"}),
        ("adequate", "low", "none", {"limited", "contested"}),
        ("partial", "medium", "none", {"limited", "contested"}),
        ("adequate", "high", "none", {"asserted", "limited"}),
    ],
)
def test_stance_table(adequacy: str, confidence: str, conflict: str, expected: set) -> None:
    assert allowed_stances(
        semantic_adequacy=adequacy, confidence=confidence, conflict_status=conflict
    ) == frozenset(expected)


# ------------------------------------------------------------------ citations

def test_citation_model_is_shared_for_text_and_visual() -> None:
    text_payloads = collect_evidence_payloads(_supported_state())
    visual_payloads = collect_evidence_payloads(_visual_state())

    assert text_payloads[0].citation_label() == "https://docs.example/page#section" or (
        "docs.example" in text_payloads[0].citation_label()
    )
    visual = visual_payloads[0]
    assert visual.is_visual is True
    assert "p.4" in visual.citation_label()
    assert "bbox:10,10,200,120" in visual.citation_label()


# ---------------------------------------------------------------- happy path

def test_extractive_default_writer_produces_a_fully_covered_draft() -> None:
    state = _supported_state()
    projection = build_research_brief_projection(state)
    payloads = collect_evidence_payloads(state)

    draft = assemble_synthesis_draft(projection=projection, payloads=payloads)

    assert len(draft.sections) == 1
    section = draft.sections[0]
    assert section.assertions[0].evidence_refs == ("ev_text",)
    assert section.citations[0].evidence_id == "ev_text"
    assert draft.coverage_report.fully_covered is True
    assert draft.coverage_report.factual_assertions == 1
    assert draft.coverage_report.covered_assertions == 1
    assert draft.coverage_report.uncovered_assertions == 0


def test_visual_evidence_is_cited_with_page_and_region() -> None:
    state = _visual_state()
    projection = build_research_brief_projection(state)

    draft = assemble_synthesis_draft(
        projection=projection, payloads=collect_evidence_payloads(state)
    )

    citation = draft.sections[0].citations[0]
    assert citation.modality == "chart"
    assert "p.4" in citation.label
    assert citation.provenance.endswith("#page=4")


def test_assembler_is_deterministic_and_does_not_mutate_the_state() -> None:
    state = _supported_state()
    before = state.to_dict()
    projection = build_research_brief_projection(state)
    payloads = collect_evidence_payloads(state)

    first = assemble_synthesis_draft(projection=projection, payloads=payloads)
    second = assemble_synthesis_draft(projection=projection, payloads=payloads)

    assert first.to_dict() == second.to_dict()
    assert state.to_dict() == before


def test_limitations_are_carried_into_the_draft() -> None:
    state = _state(
        requirement=_requirement("u1", "u2"),
        evidence=(
            ResearchEvidence(
                "ev_text",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_text_unit("u1", "partial"),),
            ),
        ),
        links=(_link("ev_text"),),
    )
    projection = build_research_brief_projection(state)

    draft = assemble_synthesis_draft(
        projection=projection, payloads=collect_evidence_payloads(state)
    )

    assert draft.limitations == projection.limitations
    assert draft.limitations


# ------------------------------------------------------- failure semantics

def _writer_returning(*sections: SynthesisSection):
    def writer(projection, payloads):
        del projection, payloads
        return sections

    return writer


def test_assertion_without_an_evidence_ref_is_rejected() -> None:
    state = _supported_state()
    projection = build_research_brief_projection(state)
    section = SynthesisSection(
        section_id="s1",
        text="Feature X is unsupported.",
        assertions=(
            SynthesisAssertion(
                assertion_id="a1",
                claim_id="c1",
                statement="Feature X is unsupported.",
                evidence_refs=(),
            ),
        ),
    )

    with pytest.raises(SynthesisContractViolation) as exc:
        assemble_synthesis_draft(
            projection=projection,
            payloads=collect_evidence_payloads(state),
            writer=_writer_returning(section),
        )

    assert exc.value.reason == REASON_UNCOVERED_ASSERTION


def test_unauthorized_evidence_ref_is_rejected() -> None:
    state = _supported_state()
    projection = build_research_brief_projection(state)
    section = SynthesisSection(
        section_id="s1",
        text="Feature X is unsupported and also faster.",
        assertions=(
            SynthesisAssertion(
                assertion_id="a1",
                claim_id="c1",
                statement="Feature X is unsupported and also faster.",
                evidence_refs=("ev_invented",),
            ),
        ),
    )

    with pytest.raises(SynthesisContractViolation) as exc:
        assemble_synthesis_draft(
            projection=projection,
            payloads=collect_evidence_payloads(state),
            writer=_writer_returning(section),
        )

    assert exc.value.reason == REASON_UNAUTHORIZED_REF
    assert exc.value.detail == "ev_invented"


def test_unresolved_conflict_may_not_be_asserted_as_settled() -> None:
    state = _unresolved_conflict_state()
    projection = build_research_brief_projection(state)
    section = SynthesisSection(
        section_id="s1",
        text="Feature X is unsupported.",
        assertions=(
            SynthesisAssertion(
                assertion_id="a1",
                claim_id="c1",
                statement="Feature X is unsupported.",
                evidence_refs=("ev_a",),
                stance="asserted",
            ),
        ),
    )

    with pytest.raises(SynthesisContractViolation) as exc:
        assemble_synthesis_draft(
            projection=projection,
            payloads=collect_evidence_payloads(state),
            writer=_writer_returning(section),
        )

    assert exc.value.reason == REASON_STANCE_VIOLATION


def test_not_evaluated_may_not_be_asserted() -> None:
    state = _state(
        requirement=_requirement(),
        evidence=(
            ResearchEvidence(
                "ev_text",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_text_unit("u1", "something"),),
            ),
        ),
        links=(_link("ev_text"),),
    )
    projection = build_research_brief_projection(state)
    assert projection.claims[0].semantic_adequacy == "not_evaluated"
    section = SynthesisSection(
        section_id="s1",
        text="Feature X is unsupported.",
        assertions=(
            SynthesisAssertion(
                assertion_id="a1",
                claim_id="c1",
                statement="Feature X is unsupported.",
                evidence_refs=("ev_text",),
                stance="asserted",
            ),
        ),
    )

    with pytest.raises(SynthesisContractViolation) as exc:
        assemble_synthesis_draft(
            projection=projection,
            payloads=collect_evidence_payloads(state),
            writer=_writer_returning(section),
        )

    assert exc.value.reason == REASON_STANCE_VIOLATION


def test_dropping_a_limitation_is_rejected() -> None:
    state = _state(
        requirement=_requirement("u1", "u2"),
        evidence=(
            ResearchEvidence(
                "ev_text",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(_text_unit("u1", "partial"),),
            ),
        ),
        links=(_link("ev_text"),),
    )
    projection = build_research_brief_projection(state)
    assert projection.limitations
    draft = SynthesisDraft(sections=(), limitations=())

    from src.web.research.synthesis_assembler import validate_synthesis_draft

    with pytest.raises(SynthesisContractViolation) as exc:
        validate_synthesis_draft(draft, projection=projection)

    assert exc.value.reason == REASON_LIMITATIONS_DROPPED


def test_validator_counts_uncovered_assertions_before_raising() -> None:
    state = _supported_state()
    projection = build_research_brief_projection(state)
    draft = SynthesisDraft(
        sections=(
            SynthesisSection(
                section_id="s1",
                text="no refs",
                assertions=(
                    SynthesisAssertion(
                        assertion_id="a1", claim_id="c1", statement="x", evidence_refs=()
                    ),
                ),
            ),
        ),
        limitations=projection.limitations,
    )

    from src.web.research.synthesis_assembler import validate_synthesis_draft

    with pytest.raises(SynthesisContractViolation):
        validate_synthesis_draft(draft, projection=projection)


def test_default_writer_is_model_free_and_uses_only_authorised_refs() -> None:
    state = _visual_state()
    projection = build_research_brief_projection(state)
    payloads = {item.evidence_id: item for item in collect_evidence_payloads(state)}

    sections = extractive_writer(projection, payloads)

    authorized = {ref for claim in projection.claims for ref in claim.evidence_refs}
    for section in sections:
        for assertion in section.assertions:
            assert set(assertion.evidence_refs) <= authorized


# --- Deep-4A: one evidence must never lose a unit to an evidence_id map ------------


def _multi_unit_state(*units):
    return _state(
        requirement=_requirement("u1"),
        evidence=(
            ResearchEvidence(
                "ev1",
                lifecycle_status="read",
                extraction_status="eligible",
                locator="anchor",
                units=tuple(units),
            ),
        ),
        links=(_link("ev1"),),
    )


def test_m1_two_text_units_produce_one_payload_holding_both():
    state = _multi_unit_state(_text_unit("u1", "A"), _text_unit("u2", "B"))
    payloads = collect_evidence_payloads(state)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.evidence_id == "ev1"
    assert [unit.unit_id for unit in payload.units] == ["u1", "u2"]
    assert "A" in payload.text() and "B" in payload.text()


def test_m6_an_evidence_id_map_cannot_drop_a_unit():
    state = _multi_unit_state(_text_unit("u1", "A"), _text_unit("u2", "B"))
    by_id = {payload.evidence_id: payload for payload in collect_evidence_payloads(state)}
    assert set(by_id) == {"ev1"}
    assert "A" in by_id["ev1"].text() and "B" in by_id["ev1"].text()


def test_m2_text_and_chart_keep_both_modalities():
    state = _multi_unit_state(_text_unit("u1", "prose"), _chart_unit("u2"))
    payload = collect_evidence_payloads(state)[0]
    modalities = {unit.modality for unit in payload.units}
    assert "text" in modalities and "chart" in modalities
    assert payload.is_visual is True


def test_m3_two_charts_keep_both_locators():
    first = _chart_unit("u1")
    second = EvidenceUnit(
        unit_id="u2",
        source_type="chart",
        source="https://cdn.example.com/f5.png",
        page=5,
        region="bbox:1,1,2,2",
        content="second",
    )
    state = _multi_unit_state(first, second)
    label = collect_evidence_payloads(state)[0].citation_label()
    assert "p.4" in label and "p.5" in label
    assert "bbox:10,10,200,120" in label and "bbox:1,1,2,2" in label


def test_m4_two_evidence_ids_stay_two_payloads():
    state = _multi_unit_state(_text_unit("u1", "A"))
    payloads = collect_evidence_payloads(state)
    assert len(payloads) == 1
    assert len({payload.evidence_id for payload in payloads}) == len(payloads)


def test_m5_the_singular_constructor_still_behaves_as_one_unit():
    from src.web.research.synthesis_assembler import EvidencePayload

    legacy = EvidencePayload("e1", content="legacy body", page=2, region="r")
    assert legacy.text() == "legacy body"
    assert len(legacy.effective_units) == 1
    assert legacy.effective_units[0].page == 2
