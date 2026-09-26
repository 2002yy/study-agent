"""§147 ResearchBrief projection: evidence state -> synthesis-facing view.

Frozen contract: ``docs/PROJECT_STATUS.md`` §147.

This is a **derived projection**, never a second research agent. It re-judges
nothing: every status/adequacy/conflict field is copied from RQ-A/C/D, and it
never searches, never infers requirements and never asks a model for a number.

Naming: the persisted, gate-owned ``ResearchBrief`` in :mod:`contracts` is left
untouched; this richer, non-persisted, synthesis-facing object is
``ResearchBriefProjection``.

Principles enforced here:

* P1 no re-judging -- values come from the assessors;
* P2 ``not_evaluated`` is never dressed up as confidence;
* P3 a ``preferred_side`` never deletes the contradicting evidence;
* P4 ``missing`` only mirrors frozen ``required_units`` or an unresolved conflict;
* P5 text and visual evidence share one reference model;
* P6 confidence is deterministic and code-owned (no model-reported numbers);
* P7 ``missing`` (claim gaps) and ``limitations`` (run-level) stay separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from src.web.research.claim_conflict_assessment import (
    assess_claim_conflict,
)
from src.web.research.claim_evidence_assessment import (
    ClaimEvidenceAssessment,
    assess_claim_evidence,
)
from src.web.research.contracts import ResearchState

BriefConfidence = Literal["not_evaluated", "unresolved", "low", "medium", "high"]

REASON_REQUIRED_UNITS_MISSING = "required_units_missing"
REASON_UNRESOLVED_CONFLICT = "unresolved_conflict"

LIMITATION_UNRESOLVED_CONFLICTS = "unresolved_conflicts_present"
LIMITATION_NO_REQUIRED_UNITS = "claims_without_declared_required_units"
LIMITATION_CRITICAL_NOT_SATISFIED = "critical_claims_not_adequately_supported"
LIMITATION_PRIMARY_SOURCE_MISSING = "primary_source_missing"
LIMITATION_UNDATED_EVIDENCE = "undated_evidence_present"
LIMITATION_BUDGET_EXHAUSTED = "budget_exhausted_before_coverage"
LIMITATION_EVIDENCE_WITHOUT_PROVENANCE = "evidence_without_provenance"

MODALITY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class BriefQuestion:
    question_id: str
    question_surface: str

    def to_dict(self) -> dict[str, Any]:
        return {"question_id": self.question_id, "question_surface": self.question_surface}


@dataclass(frozen=True)
class BriefClaim:
    claim_id: str
    statement: str
    criticality: str
    status: str
    semantic_adequacy: str
    confidence: BriefConfidence
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "criticality": self.criticality,
            "status": self.status,
            "semantic_adequacy": self.semantic_adequacy,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class BriefContradiction:
    claim_id: str
    support_refs: tuple[str, ...]
    contradict_refs: tuple[str, ...]
    conflict_status: str
    preferred_side: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "support_refs": list(self.support_refs),
            "contradict_refs": list(self.contradict_refs),
            "conflict_status": self.conflict_status,
            "preferred_side": self.preferred_side,
        }


@dataclass(frozen=True)
class BriefMissing:
    claim_id: str
    missing_required_units: tuple[str, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "missing_required_units": list(self.missing_required_units),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BriefSourceRef:
    evidence_id: str
    source: str
    locator: str
    modality: str
    provenance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "locator": self.locator,
            "modality": self.modality,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class ResearchBriefProjection:
    question: BriefQuestion | None = None
    claims: tuple[BriefClaim, ...] = ()
    contradictions: tuple[BriefContradiction, ...] = ()
    missing: tuple[BriefMissing, ...] = ()
    source_map: tuple[BriefSourceRef, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question.to_dict() if self.question else None,
            "claims": [item.to_dict() for item in self.claims],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "missing": [item.to_dict() for item in self.missing],
            "source_map": [item.to_dict() for item in self.source_map],
            "limitations": list(self.limitations),
        }


def brief_confidence(
    assessment: ClaimEvidenceAssessment,
    *,
    conflict_status: str,
) -> BriefConfidence:
    """Deterministic, explainable confidence. Never a model-reported number."""

    if assessment.semantic_adequacy == "not_evaluated":
        return "not_evaluated"
    if conflict_status == "unresolved_conflict":
        return "unresolved"
    if assessment.semantic_adequacy == "insufficient":
        return "low"
    structural_ok = assessment.supporting_clusters >= assessment.required_clusters and (
        assessment.has_primary or assessment.required_clusters == 0
    )
    if assessment.semantic_adequacy == "partial" or not structural_ok:
        return "medium"
    return "high"


def build_research_brief_projection(state: ResearchState) -> ResearchBriefProjection:
    """Project the evidence state into a synthesis-facing brief; pure."""

    question = (
        BriefQuestion(
            question_id=state.questions[0].id,
            question_surface=state.questions[0].question_surface,
        )
        if state.questions
        else None
    )

    claims: list[BriefClaim] = []
    contradictions: list[BriefContradiction] = []
    missing: list[BriefMissing] = []
    limitations: list[str] = []
    referenced: dict[str, str] = {}

    for claim in state.claims:
        assessment = assess_claim_evidence(state, claim)
        conflict = assess_claim_conflict(state, claim)

        refs = tuple(
            dict.fromkeys(
                (*assessment.supporting_evidence, *assessment.contradicting_evidence)
            )
        )
        for evidence_id in refs:
            referenced.setdefault(evidence_id, claim.id)

        claims.append(
            BriefClaim(
                claim_id=claim.id,
                statement=claim.text,
                criticality=claim.priority,
                status=assessment.state,
                semantic_adequacy=assessment.semantic_adequacy,
                confidence=brief_confidence(assessment, conflict_status=conflict.status),
                evidence_refs=refs,
            )
        )

        if conflict.status != "none":
            # P3: both sides are always preserved, preferred or not.
            contradictions.append(
                BriefContradiction(
                    claim_id=claim.id,
                    support_refs=tuple(
                        item.evidence_id for item in conflict.supporting
                    ),
                    contradict_refs=tuple(
                        item.evidence_id for item in conflict.contradicting
                    ),
                    conflict_status=conflict.status,
                    preferred_side=conflict.preferred_side,
                )
            )

        # P4: only mirror the frozen requirement / unresolved conflict.
        if assessment.missing_units:
            missing.append(
                BriefMissing(
                    claim_id=claim.id,
                    missing_required_units=tuple(
                        unit.unit_id for unit in assessment.missing_units
                    ),
                    reason=REASON_REQUIRED_UNITS_MISSING,
                )
            )
        if conflict.status == "unresolved_conflict":
            missing.append(
                BriefMissing(
                    claim_id=claim.id,
                    missing_required_units=(),
                    reason=REASON_UNRESOLVED_CONFLICT,
                )
            )

        if claim.priority == "critical":
            if assessment.semantic_adequacy == "not_evaluated":
                _add(limitations, LIMITATION_NO_REQUIRED_UNITS)
            if assessment.semantic_adequacy in {"partial", "insufficient"}:
                _add(limitations, LIMITATION_CRITICAL_NOT_SATISFIED)
            if (
                claim.evidence_requirement.requires_primary_source
                and not assessment.has_primary
            ):
                _add(limitations, LIMITATION_PRIMARY_SOURCE_MISSING)

    if any(item.conflict_status == "unresolved_conflict" for item in contradictions):
        _add(limitations, LIMITATION_UNRESOLVED_CONFLICTS)
    if _needs_dated_evidence(state) and any(
        not item.published_at for item in state.evidence
    ):
        _add(limitations, LIMITATION_UNDATED_EVIDENCE)
    if _budget_exhausted(state):
        _add(limitations, LIMITATION_BUDGET_EXHAUSTED)
    if any(not unit.provenance for item in state.evidence for unit in item.units):
        _add(limitations, LIMITATION_EVIDENCE_WITHOUT_PROVENANCE)

    return ResearchBriefProjection(
        question=question,
        claims=tuple(claims),
        contradictions=tuple(contradictions),
        missing=tuple(missing),
        source_map=_source_map(state, referenced),
        limitations=tuple(limitations),
    )


def safe_build_research_brief_projection(
    state: ResearchState,
) -> ResearchBriefProjection | None:
    """Keep shadow observability available if the projection fails."""

    try:
        return build_research_brief_projection(state)
    except Exception:  # noqa: BLE001 - a projection must never raise
        return None


def _source_map(
    state: ResearchState,
    referenced: dict[str, str],
) -> tuple[BriefSourceRef, ...]:
    """P5: text and visual evidence share one reference model."""

    refs: list[BriefSourceRef] = []
    for evidence in state.evidence:
        if evidence.evidence_id not in referenced:
            continue
        modalities = sorted({unit.source_type for unit in evidence.units})
        locator = evidence.locator or (
            evidence.units[0].provenance if evidence.units else ""
        )
        source = evidence.units[0].source if evidence.units else ""
        refs.append(
            BriefSourceRef(
                evidence_id=evidence.evidence_id,
                source=source,
                locator=locator,
                modality="+".join(modalities) if modalities else MODALITY_UNKNOWN,
                provenance=evidence.units[0].provenance if evidence.units else "",
            )
        )
    return tuple(refs)


def _needs_dated_evidence(state: ResearchState) -> bool:
    return any(
        claim.evidence_requirement.requires_dated_evidence
        or claim.evidence_requirement.max_age_days is not None
        for claim in state.claims
    )


def _budget_exhausted(state: ResearchState) -> bool:
    budget = state.budget
    return (
        budget.candidates_used >= budget.max_candidates
        or budget.reads_used >= budget.max_reads
        or budget.elapsed_seconds >= budget.hard_timeout_seconds
    )


def _add(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


__all__ = [
    "BriefClaim",
    "BriefConfidence",
    "BriefContradiction",
    "BriefMissing",
    "BriefQuestion",
    "BriefSourceRef",
    "LIMITATION_BUDGET_EXHAUSTED",
    "LIMITATION_CRITICAL_NOT_SATISFIED",
    "LIMITATION_EVIDENCE_WITHOUT_PROVENANCE",
    "LIMITATION_NO_REQUIRED_UNITS",
    "LIMITATION_PRIMARY_SOURCE_MISSING",
    "LIMITATION_UNDATED_EVIDENCE",
    "LIMITATION_UNRESOLVED_CONFLICTS",
    "MODALITY_UNKNOWN",
    "REASON_REQUIRED_UNITS_MISSING",
    "REASON_UNRESOLVED_CONFLICT",
    "ResearchBriefProjection",
    "brief_confidence",
    "build_research_brief_projection",
    "safe_build_research_brief_projection",
]
