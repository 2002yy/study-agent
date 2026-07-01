"""Structured pedagogy evaluation pipeline.

Deterministic checks remain the cheap first pass. Ambiguous learner claims are
delegated to a semantic evaluator that must return evidence-linked structure
instead of a bare correct/incorrect flag.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol
from uuid import uuid4

from src.pedagogy.evaluator import evaluate_learner_response
from src.pedagogy.types import LearningState


@dataclass(frozen=True)
class SemanticEvaluation:
    claims: tuple[str, ...] = ()
    correct_points: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    misconceptions: tuple[str, ...] = ()
    reasoning_complete: bool = False
    transfer_ready: bool = False
    confidence: float = 0.0
    evidence_refs: tuple[str, ...] = ()


class SemanticEvaluator(Protocol):
    def evaluate(
        self,
        *,
        learner_input: str,
        objective: str,
        protocol: str,
        expected_concepts: tuple[str, ...],
        evidence: tuple[str, ...],
    ) -> SemanticEvaluation: ...


@dataclass(frozen=True)
class PedagogyEvalRun:
    id: str
    learner_input: str
    objective: str
    protocol: str
    expected_concepts: tuple[str, ...]
    evidence: tuple[str, ...]
    deterministic_result: dict[str, object]
    semantic_result: SemanticEvaluation | None
    confidence: float
    final_decision: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PedagogyEvaluationService:
    def __init__(self, semantic_evaluator: SemanticEvaluator | None = None):
        self.semantic_evaluator = semantic_evaluator

    def evaluate_learner(
        self,
        *,
        learner_input: str,
        state: LearningState,
        expected_concepts: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
    ) -> PedagogyEvalRun:
        deterministic = evaluate_learner_response(learner_input, state=state)
        deterministic_payload = asdict(deterministic)

        if deterministic.misconceptions or not deterministic.is_claim:
            return self._run(
                learner_input=learner_input,
                state=state,
                expected_concepts=expected_concepts,
                evidence=evidence,
                deterministic_result=deterministic_payload,
                semantic_result=None,
                confidence=1.0,
                final_decision="reject",
                reasons=(deterministic.reason,),
            )

        if self.semantic_evaluator is None:
            return self._run(
                learner_input=learner_input,
                state=state,
                expected_concepts=expected_concepts,
                evidence=evidence,
                deterministic_result=deterministic_payload,
                semantic_result=None,
                confidence=0.0,
                final_decision="needs_semantic_review",
                reasons=("semantic_evaluator_unavailable",),
            )

        semantic = self.semantic_evaluator.evaluate(
            learner_input=learner_input,
            objective=state.objective,
            protocol=state.protocol,
            expected_concepts=expected_concepts,
            evidence=evidence,
        )
        evidence_is_grounded = not semantic.evidence_refs or all(
            ref in evidence for ref in semantic.evidence_refs
        )
        accepted = (
            semantic.reasoning_complete
            and semantic.transfer_ready
            and semantic.confidence >= 0.7
            and not semantic.misconceptions
            and evidence_is_grounded
        )
        reasons = []
        if not evidence_is_grounded:
            reasons.append("unknown_evidence_reference")
        if semantic.misconceptions:
            reasons.append("semantic_misconception")
        if not semantic.reasoning_complete:
            reasons.append("reasoning_incomplete")
        if not semantic.transfer_ready:
            reasons.append("transfer_not_ready")
        if semantic.confidence < 0.7:
            reasons.append("low_confidence")
        return self._run(
            learner_input=learner_input,
            state=state,
            expected_concepts=expected_concepts,
            evidence=evidence,
            deterministic_result=deterministic_payload,
            semantic_result=semantic,
            confidence=semantic.confidence,
            final_decision="accept" if accepted else "reject",
            reasons=tuple(reasons),
        )

    @staticmethod
    def _run(
        *,
        learner_input: str,
        state: LearningState,
        expected_concepts: tuple[str, ...],
        evidence: tuple[str, ...],
        deterministic_result: dict[str, object],
        semantic_result: SemanticEvaluation | None,
        confidence: float,
        final_decision: str,
        reasons: tuple[str, ...],
    ) -> PedagogyEvalRun:
        return PedagogyEvalRun(
            id=f"ped_eval_{uuid4().hex}",
            learner_input=learner_input,
            objective=state.objective,
            protocol=state.protocol,
            expected_concepts=expected_concepts,
            evidence=evidence,
            deterministic_result=deterministic_result,
            semantic_result=semantic_result,
            confidence=confidence,
            final_decision=final_decision,
            reasons=reasons,
        )
