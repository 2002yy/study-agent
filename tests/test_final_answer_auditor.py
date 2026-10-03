"""§149 audit: separate mechanical and semantic checks, bounded repair."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.web.research.final_answer_auditor import (
    AuditIssue,
    SemanticAssessment,
    audit_final_answer,
)
from src.web.research.research_brief_projection import (
    BriefClaim,
    BriefQuestion,
    ResearchBriefProjection,
)
from src.web.research.synthesis_assembler import (
    EvidencePayload,
    SynthesisAssertion,
    SynthesisCitation,
    SynthesisDraft,
    SynthesisSection,
)


@pytest.fixture
def case() -> tuple[SynthesisDraft, ResearchBriefProjection, tuple[EvidencePayload, ...]]:
    projection = ResearchBriefProjection(
        question=BriefQuestion("q1", "Is X supported?"),
        claims=(
            BriefClaim("c1", "X is supported.", "critical", "supported", "adequate", "high", ("e1",)),
        ),
        limitations=("dated_evidence_missing",),
    )
    draft = SynthesisDraft(
        sections=(
            SynthesisSection(
                section_id="s1",
                text="X is supported.",
                assertions=(SynthesisAssertion("a1", "c1", "X is supported.", ("e1",)),),
                citations=(SynthesisCitation("e1", "source (section 1)", "text"),),
            ),
        ),
        limitations=projection.limitations,
    )
    return draft, projection, (EvidencePayload("e1", content="X is supported."),)


def _approved(*args: object) -> SemanticAssessment:
    return SemanticAssessment(question_coverage="covered", evidence_grounding="covered")


def test_default_judge_abstains_and_cannot_approve(case) -> None:
    draft, projection, payloads = case
    result = audit_final_answer(draft=draft, projection=projection, payloads=payloads)
    assert result.verdict == "fail"
    assert result.approval_status == "audited-but-not-approved"
    assert result.question_coverage == "unverified"
    assert result.evidence_grounding == "unverified"
    assert "semantic_support_unverified" in {issue.issue_type for issue in result.issues}


def test_injected_semantic_judge_can_approve_valid_answer(case) -> None:
    draft, projection, payloads = case
    result = audit_final_answer(
        draft=draft, projection=projection, payloads=payloads, judge=_approved
    )
    assert result.verdict == "pass"
    assert result.approval_status == "approved"
    assert result.repair_allowed is False
    assert result.repair_used is False


@pytest.mark.parametrize(
    ("assessment", "expected"),
    [
        (
            SemanticAssessment(
                question_coverage="partial", evidence_grounding="covered",
                unanswered_aspects=("platform support",),
            ),
            "unanswered_aspect",
        ),
        (
            SemanticAssessment(
                question_coverage="covered", evidence_grounding="partial",
                citation_support_gaps=("e1 does not support a1",),
            ),
            "citation_support_gap",
        ),
        (
            SemanticAssessment(
                question_coverage="covered", evidence_grounding="covered",
                contradiction_gaps=("c1 opposing source omitted",),
            ),
            "contradiction_gap",
        ),
        (
            SemanticAssessment(
                question_coverage="covered", evidence_grounding="covered",
                issues=(AuditIssue("overstated", "blocking", "too strong", "a1", ("e1",)),),
            ),
            "overstated",
        ),
    ],
)
def test_semantic_failures_remain_separate_from_mechanical_gate(
    case, assessment: SemanticAssessment, expected: str
) -> None:
    draft, projection, payloads = case
    result = audit_final_answer(
        draft=draft, projection=projection, payloads=payloads,
        judge=lambda *_: assessment,
    )
    assert result.verdict == "fail"
    assert expected in {issue.issue_type for issue in result.issues}


def test_mechanical_failure_skips_semantic_judge(case) -> None:
    draft, projection, payloads = case
    broken = replace(draft, limitations=())
    calls = 0

    def judge(*args):
        nonlocal calls
        calls += 1
        return _approved()

    result = audit_final_answer(
        draft=broken, projection=projection, payloads=payloads, judge=judge
    )
    assert result.verdict == "repairable"
    assert result.issues[0].issue_type == "limitations_dropped"
    assert calls == 0


def test_citation_must_belong_to_the_assertions_claim(case) -> None:
    draft, projection, payloads = case
    other = BriefClaim(
        "c2", "Y is supported.", "supporting", "supported", "adequate", "high", ("e2",)
    )
    projection = replace(projection, claims=(*projection.claims, other))
    section = draft.sections[0]
    wrong = replace(
        section,
        assertions=(replace(section.assertions[0], evidence_refs=("e2",)),),
        citations=(SynthesisCitation("e2", "other source", "text"),),
    )
    result = audit_final_answer(
        draft=replace(draft, sections=(wrong,)), projection=projection,
        payloads=(*payloads, EvidencePayload("e2", content="Y is supported.")),
        judge=_approved,
    )
    assert result.verdict == "repairable"
    assert result.issues[0].issue_type == "unauthorized_evidence_ref"


def test_empty_answer_cannot_pass_by_dropping_critical_claim(case) -> None:
    draft, projection, payloads = case
    result = audit_final_answer(
        draft=replace(draft, sections=()), projection=projection,
        payloads=payloads, judge=_approved,
    )
    assert result.verdict == "fail"
    assert result.question_coverage == "partial"
    assert result.unanswered_aspects == ("c1",)


def test_repair_runs_once_and_can_restore_limitation(case) -> None:
    draft, projection, payloads = case
    broken = replace(draft, limitations=())
    calls = 0

    def repairer(current, result):
        nonlocal calls
        calls += 1
        assert result.repair_allowed
        return replace(current, limitations=projection.limitations)

    result = audit_final_answer(
        draft=broken, projection=projection, payloads=payloads,
        judge=_approved, repairer=repairer,
    )
    assert calls == 1
    assert result.verdict == "pass"
    assert result.repair_used is True
    assert result.repair_allowed is False
    assert result.audited_draft.limitations == projection.limitations


def test_failed_repair_stops_after_one_attempt_and_keeps_reason(case) -> None:
    draft, projection, payloads = case
    broken = replace(draft, limitations=())
    calls = 0

    def repairer(current, result):
        nonlocal calls
        calls += 1
        return current

    result = audit_final_answer(
        draft=broken, projection=projection, payloads=payloads,
        judge=_approved, repairer=repairer,
    )
    assert calls == 1
    assert result.verdict == "fail"
    assert result.approval_status == "audited-but-not-approved"
    assert result.repair_allowed is False
    assert result.previous_issues[0].issue_type == "limitations_dropped"
    assert result.issues[0].issue_type == "limitations_dropped"


def test_repair_cannot_add_new_assertion_or_evidence(case) -> None:
    draft, projection, payloads = case
    broken = replace(draft, limitations=())

    def repairer(current, result):
        section = current.sections[0]
        invented = SynthesisAssertion("a2", "c1", "Invented.", ("e2",))
        return replace(
            current, limitations=projection.limitations,
            sections=(replace(section, assertions=(*section.assertions, invented)),),
        )

    result = audit_final_answer(
        draft=broken, projection=projection, payloads=payloads,
        judge=_approved, repairer=repairer,
    )
    assert result.verdict == "fail"
    assert result.repair_used is True
    assert result.issues[-1].issue_type == "repair_failed"


def test_visual_citation_requires_page_and_region(case) -> None:
    draft, projection, _ = case
    visual = EvidencePayload("e1", modality="chart", page=4, region="figure 2")
    result = audit_final_answer(
        draft=draft, projection=projection, payloads=(visual,), judge=_approved
    )
    assert result.verdict == "repairable"
    assert result.issues[0].issue_type == "visual_locator_missing"

    no_locator = replace(visual, region="")
    result = audit_final_answer(
        draft=draft, projection=projection, payloads=(no_locator,), judge=_approved
    )
    assert result.verdict == "fail"


def test_judge_exception_fails_closed(case) -> None:
    draft, projection, payloads = case

    def judge(*args):
        raise RuntimeError("judge unavailable")

    result = audit_final_answer(
        draft=draft, projection=projection, payloads=payloads, judge=judge
    )
    assert result.verdict == "fail"
    assert result.issues[0].issue_type == "semantic_judge_failed"
