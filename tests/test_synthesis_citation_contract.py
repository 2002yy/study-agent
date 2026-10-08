"""RP-1 S3: preserve authorized refs, distinguish unanswered claims, fail closed."""

from dataclasses import replace

import pytest

from src.web.research.final_answer_auditor import audit_final_answer
from src.web.research.research_brief_projection import (
    BriefClaim,
    ResearchBriefProjection,
)
from src.web.research.synthesis_assembler import (
    REASON_CITATION_MISSING,
    REASON_UNAUTHORIZED_REF,
    REASON_UNCOVERED_ASSERTION,
    EvidencePayload,
    SynthesisAssertion,
    SynthesisCitation,
    SynthesisContractViolation,
    SynthesisSection,
    assemble_synthesis_draft,
    extractive_writer,
)


def case():
    # Contract fixture, not evidence that an actual Opus fact is verified.
    claim = BriefClaim(
        "s3-known",
        "测试版本字段为5.5",
        "critical",
        "supported",
        "adequate",
        "high",
        ("e1",),
    )
    payload = EvidencePayload(
        "e1",
        source="https://example.com/version",
        locator="#version",
        provenance="fixture-body-sha256:abc",
        content="测试版本字段为5.5",
    )
    return ResearchBriefProjection(
        claims=(claim,), limitations=("fixture_not_real_research",)
    ), payload


def test_supported_claim_keeps_reference_locator_and_provenance():
    projection, payload = case()
    draft = assemble_synthesis_draft(projection=projection, payloads=(payload,))
    assertion = draft.sections[0].assertions[0]
    citation = draft.sections[0].citations[0]
    assert assertion.claim_id == projection.claims[0].claim_id
    assert assertion.evidence_refs == (payload.evidence_id,)
    assert citation.evidence_id == payload.evidence_id
    assert citation.provenance == payload.provenance
    assert citation.label == payload.citation_label()
    assert draft.sections[0].text == payload.content
    assert draft.limitations == projection.limitations


def test_real_s3_no_ref_shape_is_pending_not_a_factual_assertion():
    # Control fields copied from the recorded S3 projection; no supporting URL added.
    claim = BriefClaim(
        "claim_b515a8ffb15688c23a2e7e4a",
        "Opus 5.5 发布日期、版本号和定位",
        "critical",
        "unresolved",
        "not_evaluated",
        "not_evaluated",
        (),
    )
    projection = ResearchBriefProjection(claims=(claim,))
    draft = assemble_synthesis_draft(projection=projection, payloads=())
    assert draft.sections[0].section_id == f"claim:{claim.claim_id}"
    assert "待核验问题（尚未取得可引用证据）" in draft.sections[0].text
    assert draft.sections[0].assertions == draft.sections[0].citations == ()
    assert draft.coverage_report.factual_assertions == 0
    audit = audit_final_answer(draft=draft, projection=projection, payloads=())
    assert audit.verdict == "fail"
    assert audit.approval_status == "audited-but-not-approved"
    assert {issue.issue_type for issue in audit.issues} == {
        "critical_question_unanswered"
    }


def test_unbound_payloads_cannot_be_borrowed_for_a_pending_claim():
    projection, payload = case()
    projection = replace(
        projection, claims=(replace(projection.claims[0], evidence_refs=()),)
    )
    draft = assemble_synthesis_draft(projection=projection, payloads=(payload,))
    assert draft.sections[0].assertions == draft.sections[0].citations == ()
    assert payload.content not in draft.sections[0].text.replace(
        projection.claims[0].statement, ""
    )


def test_missing_authorized_payload_cannot_be_silently_dropped():
    projection, payload = case()
    projection = replace(
        projection,
        claims=(replace(projection.claims[0], evidence_refs=("e1", "missing")),),
    )
    with pytest.raises(SynthesisContractViolation) as error:
        assemble_synthesis_draft(projection=projection, payloads=(payload,))
    assert error.value.reason == REASON_CITATION_MISSING
    assert error.value.detail.endswith(":missing")


def test_a_writer_cannot_emit_a_fact_without_a_reference():
    projection, payload = case()

    def invalid_writer(brief, payloads):
        return (
            SynthesisSection(
                "fact", "测试事实", (SynthesisAssertion("a", "s3-known", "测试事实"),)
            ),
        )

    with pytest.raises(SynthesisContractViolation) as error:
        assemble_synthesis_draft(
            projection=projection, payloads=(payload,), writer=invalid_writer
        )
    assert error.value.reason == REASON_UNCOVERED_ASSERTION


def test_existing_reference_for_another_claim_is_rejected():
    projection, payload = case()
    other = replace(payload, evidence_id="e2", content="不同问题的测试资料")

    def wrong_writer(brief, payloads):
        return (
            SynthesisSection(
                "fact",
                "错误绑定",
                (SynthesisAssertion("a", "s3-known", "测试事实", ("e2",)),),
                (
                    SynthesisCitation(
                        "e2", other.citation_label(), "text", other.provenance
                    ),
                ),
            ),
        )

    with pytest.raises(SynthesisContractViolation) as error:
        assemble_synthesis_draft(
            projection=projection, payloads=(payload, other), writer=wrong_writer
        )
    assert error.value.reason == REASON_UNAUTHORIZED_REF


def test_structural_reference_does_not_grant_semantic_support():
    projection, payload = case()
    unrelated = replace(payload, content="这份资料没有证明请求的版本字段")
    draft = assemble_synthesis_draft(projection=projection, payloads=(unrelated,))
    audit = audit_final_answer(
        draft=draft, projection=projection, payloads=(unrelated,)
    )
    assert audit.verdict == "fail"
    assert audit.evidence_grounding == "unverified"
    assert "semantic_support_unverified" in {issue.issue_type for issue in audit.issues}


def test_partial_coverage_preserves_supported_refs_and_unanswered_claim_identity():
    projection, payload = case()
    missing = BriefClaim(
        "s3-missing",
        "尚待查证的发布日期",
        "critical",
        "unresolved",
        "not_evaluated",
        "not_evaluated",
        (),
    )
    projection = replace(projection, claims=(*projection.claims, missing))
    before = projection.to_dict()
    draft = assemble_synthesis_draft(projection=projection, payloads=(payload,))
    assert draft.sections[0].assertions[0].evidence_refs == ("e1",)
    assert draft.sections[1].section_id == "claim:s3-missing"
    assert not draft.sections[1].assertions and not draft.sections[1].citations
    assert draft.coverage_report.factual_assertions == 1
    # Mechanical coverage of the emitted assertions is not whole-question approval.
    audit = audit_final_answer(draft=draft, projection=projection, payloads=(payload,))
    assert audit.verdict == "fail"
    assert "critical_question_unanswered" in {
        issue.issue_type for issue in audit.issues
    }
    assert projection.to_dict() == before
    assert extractive_writer(projection, {"e1": payload}) == draft.sections
