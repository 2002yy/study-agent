"""Structured pedagogy evaluation pipeline.

Deterministic checks remain the cheap first pass. Ambiguous learner claims are
delegated to a semantic evaluator that must return evidence-linked structure
instead of a bare correct/incorrect flag.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol
from uuid import uuid4

from src.llm_client import chat
from src.pedagogy.evaluator import evaluate_learner_response
from src.pedagogy.types import LearningState

EVALUATOR_VERSION = "pedagogy-eval-v1"
SEMANTIC_PROMPT_VERSION = "pedagogy-semantic-v1"
SEMANTIC_SCHEMA_VERSION = "1"


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


class LLMSemanticEvaluator:
    """Strict JSON adapter for ambiguous learner claims."""

    evaluator_version = EVALUATOR_VERSION
    prompt_version = SEMANTIC_PROMPT_VERSION
    schema_version = SEMANTIC_SCHEMA_VERSION

    def __init__(self, complete: Callable[..., str] = chat):
        self.complete = complete

    def evaluate(
        self,
        *,
        learner_input: str,
        objective: str,
        protocol: str,
        expected_concepts: tuple[str, ...],
        evidence: tuple[str, ...],
    ) -> SemanticEvaluation:
        payload = {
            "objective": objective,
            "protocol": protocol,
            "learner_input": learner_input,
            "expected_concepts": list(expected_concepts),
            "allowed_evidence_refs": list(evidence),
        }
        raw = self.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Evaluate conceptual understanding. Return one JSON object with "
                        "claims, correct_points, gaps, misconceptions, reasoning_complete, "
                        "transfer_ready, confidence, and evidence_refs. Arrays contain "
                        "strings; booleans are strict; confidence is 0..1. Evidence refs "
                        "must come only from allowed_evidence_refs. Do not infer mastery "
                        "from fluency or phrases such as 'I understand'."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            task_name="pedagogy_evaluation",
        )
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Semantic evaluator returned a non-object")
        return SemanticEvaluation(
            claims=_strings(data.get("claims")),
            correct_points=_strings(data.get("correct_points")),
            gaps=_strings(data.get("gaps")),
            misconceptions=_strings(data.get("misconceptions")),
            reasoning_complete=data.get("reasoning_complete") is True,
            transfer_ready=data.get("transfer_ready") is True,
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
            evidence_refs=_strings(data.get("evidence_refs")),
        )


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
    evaluator_version: str = EVALUATOR_VERSION
    prompt_version: str = SEMANTIC_PROMPT_VERSION
    schema_version: str = SEMANTIC_SCHEMA_VERSION

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

        try:
            semantic = self.semantic_evaluator.evaluate(
                learner_input=learner_input,
                objective=state.objective,
                protocol=state.protocol,
                expected_concepts=expected_concepts,
                evidence=evidence,
            )
        except Exception as exc:
            return self._run(
                learner_input=learner_input,
                state=state,
                expected_concepts=expected_concepts,
                evidence=evidence,
                deterministic_result=deterministic_payload,
                semantic_result=None,
                confidence=0.0,
                final_decision="needs_semantic_review",
                reasons=(f"semantic_evaluator_failed:{type(exc).__name__}",),
            )
        evidence_is_grounded = (
            not evidence and not semantic.evidence_refs
        ) or (
            bool(semantic.evidence_refs)
            and all(ref in evidence for ref in semantic.evidence_refs)
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
            reasons.append(
                "unknown_evidence_reference"
                if semantic.evidence_refs
                else "missing_evidence_reference"
            )
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


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())
