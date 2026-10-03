"""§149 final-answer audit. Mechanical checks and semantic judgement stay separate.

The default semantic judge abstains: code cannot establish that a citation really
supports a sentence or that prose answers the user's question. A caller may inject
a judge for those decisions. No path here searches, reads, or changes research state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable, Literal, Mapping

from src.web.research.research_brief_projection import ResearchBriefProjection
from src.web.research.synthesis_assembler import (
    EvidencePayload,
    REASON_VISUAL_LOCATOR_MISSING,
    SynthesisContractViolation,
    SynthesisDraft,
    validate_synthesis_draft,
)

AuditVerdict = Literal["pass", "repairable", "fail"]
AuditDimension = Literal["covered", "partial", "unverified"]


@dataclass(frozen=True)
class AuditIssue:
    issue_type: str
    severity: Literal["blocking", "warning"]
    reason: str
    assertion_id: str = ""
    evidence_refs: tuple[str, ...] = ()
    repairable: bool = False


@dataclass(frozen=True)
class SemanticAssessment:
    """A judge's explicit assessment, independent of mechanical validation."""

    issues: tuple[AuditIssue, ...] = ()
    unanswered_aspects: tuple[str, ...] = ()
    contradiction_gaps: tuple[str, ...] = ()
    citation_support_gaps: tuple[str, ...] = ()
    question_coverage: AuditDimension = "unverified"
    evidence_grounding: AuditDimension = "unverified"


@dataclass(frozen=True)
class AuditResult:
    verdict: AuditVerdict
    issues: tuple[AuditIssue, ...]
    unanswered_aspects: tuple[str, ...]
    contradiction_gaps: tuple[str, ...]
    citation_support_gaps: tuple[str, ...]
    question_coverage: AuditDimension
    evidence_grounding: AuditDimension
    repair_allowed: bool
    audited_draft: SynthesisDraft
    repair_used: bool = False
    previous_issues: tuple[AuditIssue, ...] = ()

    @property
    def approval_status(self) -> Literal["approved", "audited-but-not-approved"]:
        return "approved" if self.verdict == "pass" else "audited-but-not-approved"


SemanticJudge = Callable[
    [SynthesisDraft, ResearchBriefProjection, Mapping[str, EvidencePayload]],
    SemanticAssessment,
]
BoundedRepairer = Callable[[SynthesisDraft, AuditResult], SynthesisDraft]


def abstaining_judge(
    draft: SynthesisDraft,
    projection: ResearchBriefProjection,
    payloads: Mapping[str, EvidencePayload],
) -> SemanticAssessment:
    """Fail closed when no semantic judge is supplied; never guess support."""

    del payloads
    return SemanticAssessment(
        issues=tuple(
            AuditIssue(
                issue_type="semantic_support_unverified",
                severity="blocking",
                reason="No semantic judge verified that the cited evidence supports this assertion.",
                assertion_id=assertion.assertion_id,
                evidence_refs=assertion.evidence_refs,
            )
            for section in draft.sections
            for assertion in section.assertions
        ),
        unanswered_aspects=(
            (projection.question.question_surface,)
            if projection.question is not None
            else ("question_not_available",)
        ),
        question_coverage="unverified",
        evidence_grounding="unverified",
    )


def audit_final_answer(
    *,
    draft: SynthesisDraft,
    projection: ResearchBriefProjection,
    payloads: Iterable[EvidencePayload],
    judge: SemanticJudge | None = None,
    repairer: BoundedRepairer | None = None,
) -> AuditResult:
    """Audit once and optionally run exactly one bounded repair and re-audit."""

    by_id = {payload.evidence_id: payload for payload in payloads}
    initial = _audit_once(draft, projection, by_id, judge or abstaining_judge)
    if initial.verdict != "repairable" or repairer is None:
        return initial

    try:
        repaired = repairer(draft, initial)
        _validate_repair_scope(draft, repaired, projection)
    except Exception as exc:  # noqa: BLE001 - repair must fail closed
        failure = AuditIssue(
            issue_type="repair_failed",
            severity="blocking",
            reason=f"{type(exc).__name__}: {exc}",
        )
        return replace(
            initial,
            verdict="fail",
            issues=(*initial.issues, failure),
            repair_allowed=False,
            repair_used=True,
            previous_issues=initial.issues,
        )

    second = _audit_once(repaired, projection, by_id, judge or abstaining_judge)
    return replace(
        second,
        verdict="pass" if second.verdict == "pass" else "fail",
        repair_allowed=False,
        repair_used=True,
        previous_issues=initial.issues,
    )


def _audit_once(
    draft: SynthesisDraft,
    projection: ResearchBriefProjection,
    payloads: Mapping[str, EvidencePayload],
    judge: SemanticJudge,
) -> AuditResult:
    try:
        validate_synthesis_draft(draft, projection=projection, payloads=payloads)
    except SynthesisContractViolation as exc:
        issue = AuditIssue(
            issue_type=exc.reason,
            severity="blocking",
            reason=exc.detail or exc.reason,
            assertion_id=exc.detail.split(":", 1)[0] if ":" in exc.detail else "",
            evidence_refs=(),
            repairable=(
                exc.reason != REASON_VISUAL_LOCATOR_MISSING
                or _visual_locator_can_be_repaired(exc.detail, payloads)
            ),
        )
        return _result(
            draft,
            issues=(issue,),
            question_coverage="unverified",
            evidence_grounding="unverified",
        )

    represented_claims = {
        assertion.claim_id
        for section in draft.sections
        for assertion in section.assertions
    }
    missing_critical = tuple(
        claim.claim_id for claim in projection.claims
        if claim.criticality == "critical" and claim.claim_id not in represented_claims
    )
    if missing_critical:
        return _result(
            draft,
            issues=tuple(
                AuditIssue(
                    issue_type="critical_question_unanswered",
                    severity="blocking",
                    reason=claim_id,
                )
                for claim_id in missing_critical
            ),
            question_coverage="partial",
            evidence_grounding="unverified",
            unanswered_aspects=missing_critical,
        )
    try:
        semantic = judge(draft, projection, payloads)
        if not isinstance(semantic, SemanticAssessment):
            raise TypeError("semantic judge must return SemanticAssessment")
    except Exception as exc:  # noqa: BLE001 - judge failure cannot approve
        semantic = SemanticAssessment(
            issues=(
                AuditIssue(
                    issue_type="semantic_judge_failed",
                    severity="blocking",
                    reason=f"{type(exc).__name__}: {exc}",
                ),
            ),
        )

    issues = list(semantic.issues)
    if semantic.question_coverage != "covered" and not semantic.unanswered_aspects:
        issues.append(
            AuditIssue(
                issue_type="question_coverage_incomplete",
                severity="blocking",
                reason=semantic.question_coverage,
            )
        )
    if semantic.evidence_grounding != "covered" and not semantic.citation_support_gaps:
        issues.append(
            AuditIssue(
                issue_type="evidence_grounding_incomplete",
                severity="blocking",
                reason=semantic.evidence_grounding,
            )
        )
    for issue_type, gaps in (
        ("unanswered_aspect", semantic.unanswered_aspects),
        ("contradiction_gap", semantic.contradiction_gaps),
        ("citation_support_gap", semantic.citation_support_gaps),
    ):
        issues.extend(
            AuditIssue(issue_type=issue_type, severity="blocking", reason=gap)
            for gap in gaps
        )
    return _result(
        draft,
        issues=tuple(issues),
        question_coverage=semantic.question_coverage,
        evidence_grounding=semantic.evidence_grounding,
        unanswered_aspects=semantic.unanswered_aspects,
        contradiction_gaps=semantic.contradiction_gaps,
        citation_support_gaps=semantic.citation_support_gaps,
    )


def _result(
    draft: SynthesisDraft,
    *,
    issues: tuple[AuditIssue, ...],
    question_coverage: AuditDimension,
    evidence_grounding: AuditDimension,
    unanswered_aspects: tuple[str, ...] = (),
    contradiction_gaps: tuple[str, ...] = (),
    citation_support_gaps: tuple[str, ...] = (),
) -> AuditResult:
    blocking = tuple(issue for issue in issues if issue.severity == "blocking")
    verdict: AuditVerdict = (
        "pass" if not blocking else "repairable" if all(
            issue.repairable for issue in blocking
        ) else "fail"
    )
    return AuditResult(
        verdict=verdict,
        issues=issues,
        unanswered_aspects=unanswered_aspects,
        contradiction_gaps=contradiction_gaps,
        citation_support_gaps=citation_support_gaps,
        question_coverage=question_coverage,
        evidence_grounding=evidence_grounding,
        repair_allowed=verdict == "repairable",
        audited_draft=draft,
    )


def _visual_locator_can_be_repaired(
    detail: str, payloads: Mapping[str, EvidencePayload]
) -> bool:
    ref = detail.split(":", 1)[-1]
    payload = payloads.get(ref)
    return payload is not None and payload.page is not None and bool(payload.region)


def _validate_repair_scope(
    original: SynthesisDraft,
    repaired: SynthesisDraft,
    projection: ResearchBriefProjection,
) -> None:
    if not isinstance(repaired, SynthesisDraft):
        raise ValueError("repair must return SynthesisDraft")
    old_sections = {section.section_id: section for section in original.sections}
    old_assertions = {
        assertion.assertion_id: assertion
        for section in original.sections
        for assertion in section.assertions
    }
    allowed_refs = {
        claim.claim_id: set(claim.evidence_refs) for claim in projection.claims
    }
    if not set(repaired.limitations) <= set(projection.limitations):
        raise ValueError("repair introduced a new limitation")
    for section in repaired.sections:
        if section.section_id not in old_sections:
            raise ValueError("repair introduced a new section")
        for assertion in section.assertions:
            old = old_assertions.get(assertion.assertion_id)
            if old is None or old.claim_id != assertion.claim_id:
                raise ValueError("repair introduced a new claim or assertion")
            if not set(assertion.evidence_refs) <= allowed_refs.get(assertion.claim_id, set()):
                raise ValueError("repair introduced new evidence")
        referenced = {
            ref for assertion in section.assertions for ref in assertion.evidence_refs
        }
        if any(citation.evidence_id not in referenced for citation in section.citations):
            raise ValueError("repair introduced an unrelated citation")


__all__ = [
    "AuditIssue",
    "AuditResult",
    "BoundedRepairer",
    "SemanticAssessment",
    "SemanticJudge",
    "abstaining_judge",
    "audit_final_answer",
]
