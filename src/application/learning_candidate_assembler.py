"""§164-B: turn facts in, one proposal artifact out.

This module does exactly one thing: translate facts the chat turn has already
produced (a ``PedagogyEvalRun``, the objective, the detected misconceptions and
the source turn) into a ``LearningClosureCandidate``.

It deliberately cannot:

- call a model again, or make any new semantic judgement;
- create or focus a durable goal;
- decide mastery;
- reach the truth repository or the closure commit path.

It is a pure projection, so the same inputs always produce the same semantic
fingerprint. The bridge stops at the closure boundary: nothing here commits.
"""

from __future__ import annotations

from typing import Mapping, Sequence
from uuid import uuid4

from src.domain.learning_closure_candidate import (
    ABSTAIN_CONFLICTING_EVIDENCE,
    ABSTAIN_EVALUATOR_UNCERTAIN,
    ABSTAIN_INSUFFICIENT_RESPONSE,
    ABSTAIN_NO_AUTHORITATIVE_EVIDENCE,
    ABSTAIN_OUTSIDE_OBJECTIVE,
    AUTHORITY_REQUIRED_CLOSURE_REVIEW,
    CandidateAbstention,
    DIMENSION_UNDERSTANDING,
    LearningClosureCandidate,
    Proposal,
    ProposedMisconception,
    ProposedNextStep,
    ProposedUnderstanding,
    semantic_fingerprint,
)
from src.pedagogy.evaluation import PedagogyEvalRun

ASSEMBLER_VERSION = "learning-candidate-assembler-v1"

# final_decision -> proposed result. "needs_semantic_review" never becomes a
# result: it abstains, because there is no evaluation to cite.
_DECISION_TO_RESULT = {"accept": "pass", "reject": "fail"}

# semantic_review_status -> abstention reason for an undecided evaluation.
_UNDECIDED_REASON = {
    "unavailable": ABSTAIN_EVALUATOR_UNCERTAIN,
    "attempted_failed": ABSTAIN_EVALUATOR_UNCERTAIN,
    "blocked_by_policy": ABSTAIN_NO_AUTHORITATIVE_EVIDENCE,
}


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _misconception_labels(pedagogy_eval: PedagogyEvalRun) -> tuple[str, ...]:
    labels = list(_strings(pedagogy_eval.deterministic_result.get("misconceptions")))
    if pedagogy_eval.semantic_result is not None:
        labels.extend(pedagogy_eval.semantic_result.misconceptions)
    seen: list[str] = []
    for label in labels:
        if label not in seen:
            seen.append(label)
    return tuple(seen)


def _ungrounded_evidence(pedagogy_eval: PedagogyEvalRun) -> bool:
    """True when the evaluation cites evidence the turn was not allowed to use."""
    semantic = pedagogy_eval.semantic_result
    if semantic is None or not semantic.evidence_refs:
        return False
    allowed = set(pedagogy_eval.evidence)
    return not all(ref in allowed for ref in semantic.evidence_refs)


def assemble_closure_candidate(
    *,
    pedagogy_eval: PedagogyEvalRun,
    source_turn_id: str,
    goal_ref: str = "",
    objective_ref: str = "",
    conflicting_evidence_refs: Sequence[str] = (),
    provenance: Mapping[str, object] | None = None,
    candidate_id: str | None = None,
) -> LearningClosureCandidate:
    """Translate one turn's facts into a proposal artifact. Never commits."""
    eval_ref = pedagogy_eval.id
    objective_ref = objective_ref or _text(pedagogy_eval.objective)
    proposals: list[Proposal] = []
    abstentions: list[CandidateAbstention] = []
    basis = tuple(pedagogy_eval.reasons)

    response = _text(pedagogy_eval.learner_input)
    is_claim = pedagogy_eval.deterministic_result.get("is_claim")
    conflicts = tuple(ref for ref in conflicting_evidence_refs if str(ref).strip())

    # One dimension at a time: an abstention here does not void the candidate.
    if not response or is_claim is False:
        abstentions.append(CandidateAbstention(
            dimension=DIMENSION_UNDERSTANDING,
            reason=ABSTAIN_INSUFFICIENT_RESPONSE,
            detail="learner response is empty or is not a claim",
        ))
    elif not objective_ref:
        abstentions.append(CandidateAbstention(
            dimension=DIMENSION_UNDERSTANDING,
            reason=ABSTAIN_OUTSIDE_OBJECTIVE,
            detail="turn has no objective to attribute understanding to",
        ))
    elif conflicts:
        abstentions.append(CandidateAbstention(
            dimension=DIMENSION_UNDERSTANDING,
            reason=ABSTAIN_CONFLICTING_EVIDENCE,
            detail=",".join(conflicts),
        ))
    elif _ungrounded_evidence(pedagogy_eval):
        abstentions.append(CandidateAbstention(
            dimension=DIMENSION_UNDERSTANDING,
            reason=ABSTAIN_NO_AUTHORITATIVE_EVIDENCE,
            detail="unknown_evidence_reference",
        ))
    else:
        result = _DECISION_TO_RESULT.get(pedagogy_eval.final_decision)
        if result is None:
            abstentions.append(CandidateAbstention(
                dimension=DIMENSION_UNDERSTANDING,
                reason=_UNDECIDED_REASON.get(
                    pedagogy_eval.semantic_review_status, ABSTAIN_EVALUATOR_UNCERTAIN
                ),
                detail=pedagogy_eval.semantic_review_status or "undecided",
            ))
        else:
            proposals.append(ProposedUnderstanding(
                objective_ref=objective_ref,
                claim_ref=f"{eval_ref}:claim",
                proposed_result=result,
                pedagogy_eval_ref=eval_ref,
                basis=basis,
            ))

    for label in _misconception_labels(pedagogy_eval):
        proposals.append(ProposedMisconception(
            description=label, pedagogy_eval_ref=eval_ref, basis=basis,
        ))

    understanding = [
        item for item in proposals if isinstance(item, ProposedUnderstanding)
    ]
    understanding_abstained = any(
        item.dimension == DIMENSION_UNDERSTANDING for item in abstentions
    )
    if understanding and understanding[0].proposed_result == "fail":
        proposals.append(ProposedNextStep(
            action="revisit_objective",
            rationale="the proposed result is fail for this objective",
            pedagogy_eval_ref=eval_ref,
        ))
    elif understanding and understanding[0].proposed_result == "partial":
        proposals.append(ProposedNextStep(
            action="targeted_practice",
            rationale="the proposed result is partial for this objective",
            pedagogy_eval_ref=eval_ref,
        ))
    elif understanding_abstained and any(
        item.reason == ABSTAIN_NO_AUTHORITATIVE_EVIDENCE for item in abstentions
    ):
        proposals.append(ProposedNextStep(
            action="research",
            rationale="no authoritative evidence for the claim under evaluation",
            pedagogy_eval_ref=eval_ref,
        ))

    authority_requirements = (
        (AUTHORITY_REQUIRED_CLOSURE_REVIEW,) if proposals else ()
    )
    fingerprint = semantic_fingerprint(
        goal_ref=goal_ref,
        objective_ref=objective_ref,
        proposals=proposals,
        abstentions=abstentions,
        source_turn_ids=(source_turn_id,),
        pedagogy_eval_refs=(eval_ref,),
        authority_requirements=authority_requirements,
    )
    return LearningClosureCandidate(
        candidate_id=candidate_id or f"lcc_{uuid4().hex}",
        goal_ref=goal_ref,
        objective_ref=objective_ref,
        proposals=tuple(proposals),
        abstentions=tuple(abstentions),
        source_turn_ids=(source_turn_id,),
        pedagogy_eval_refs=(eval_ref,),
        authority_requirements=authority_requirements,
        provenance=dict(provenance or {}),
        semantic_fingerprint=fingerprint,
    )
