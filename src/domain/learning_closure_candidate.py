"""§164-B: the proposal artifact that bridges a chat turn to closure review.

A candidate says "here is what we would propose writing into durable learning
truth". It is not an evaluation, not a decision and not a truth entity:

- it may only propose, so no field here can mean committed;
- it carries no mastery, qualification or durable identity;
- ``candidate_id`` is a proposal-artifact id, never a learning-truth entity id,
  and may disappear with the candidate;
- every proposal points back at the evaluation that produced it instead of
  restating it as fact.

Closure review and ``ClosureTruthService`` remain the only path from a proposal
to durable truth; this module never reaches them.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

# Abstention taxonomy (164.5). Each reason routes somewhere concrete so that
# abstaining is a product behaviour rather than a dead state.
ABSTAIN_NO_AUTHORITATIVE_EVIDENCE = "ABSTAIN_NO_AUTHORITATIVE_EVIDENCE"
ABSTAIN_CONFLICTING_EVIDENCE = "ABSTAIN_CONFLICTING_EVIDENCE"
ABSTAIN_INSUFFICIENT_RESPONSE = "ABSTAIN_INSUFFICIENT_RESPONSE"
ABSTAIN_OUTSIDE_OBJECTIVE = "ABSTAIN_OUTSIDE_OBJECTIVE"
ABSTAIN_EVALUATOR_UNCERTAIN = "ABSTAIN_EVALUATOR_UNCERTAIN"

ABSTAIN_REASONS: tuple[str, ...] = (
    ABSTAIN_NO_AUTHORITATIVE_EVIDENCE,
    ABSTAIN_CONFLICTING_EVIDENCE,
    ABSTAIN_INSUFFICIENT_RESPONSE,
    ABSTAIN_OUTSIDE_OBJECTIVE,
    ABSTAIN_EVALUATOR_UNCERTAIN,
)

ABSTAIN_ROUTING: Mapping[str, str] = {
    ABSTAIN_NO_AUTHORITATIVE_EVIDENCE: "research",
    ABSTAIN_CONFLICTING_EVIDENCE: "research_or_manual_review",
    ABSTAIN_INSUFFICIENT_RESPONSE: "ask_learner_or_exercise",
    ABSTAIN_OUTSIDE_OBJECTIVE: "no_learner_truth_update",
    ABSTAIN_EVALUATOR_UNCERTAIN: "bounded_evaluator_retry_or_human",
}

DIMENSION_UNDERSTANDING = "understanding"
DIMENSION_MISCONCEPTION = "misconception"
DIMENSION_NEXT_STEP = "next_step"

PROPOSED_RESULTS: tuple[str, ...] = ("pass", "partial", "fail")

AUTHORITY_REQUIRED_CLOSURE_REVIEW = "closure_review"

# Names that would turn a proposal into an authority. They must not exist on any
# candidate object, and the tests assert that at the schema level.
FORBIDDEN_CANDIDATE_FIELDS: frozenset[str] = frozenset({
    "committed", "mastery", "mastered", "qualified", "qualified_judge",
    "durable_id", "truth_id", "understanding_evidence_id", "next_step_id",
    "goal_id", "label", "semantic_label", "approved",
})


def _canonical(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ProposedUnderstanding:
    """A proposed result for one objective, citing the evaluation behind it."""

    objective_ref: str
    claim_ref: str
    proposed_result: str
    pedagogy_eval_ref: str
    basis: tuple[str, ...] = ()
    authority_required: str = AUTHORITY_REQUIRED_CLOSURE_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": DIMENSION_UNDERSTANDING,
            "objective_ref": self.objective_ref,
            "claim_ref": self.claim_ref,
            "proposed_result": self.proposed_result,
            "pedagogy_eval_ref": self.pedagogy_eval_ref,
            "basis": list(self.basis),
            "authority_required": self.authority_required,
        }


@dataclass(frozen=True)
class ProposedMisconception:
    """A suspected misconception. Lifecycle states belong to 168, not here.

    The field is `description` rather than `label`: `label` is reserved for
    the semantic-label authority, and a misconception proposal is not one.
    """

    description: str
    pedagogy_eval_ref: str
    basis: tuple[str, ...] = ()
    authority_required: str = AUTHORITY_REQUIRED_CLOSURE_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": DIMENSION_MISCONCEPTION,
            "description": self.description,
            "pedagogy_eval_ref": self.pedagogy_eval_ref,
            "basis": list(self.basis),
            "authority_required": self.authority_required,
        }


@dataclass(frozen=True)
class ProposedNextStep:
    """A proposed next action. It is not the durable primary next step."""

    action: str
    rationale: str
    pedagogy_eval_ref: str
    authority_required: str = AUTHORITY_REQUIRED_CLOSURE_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": DIMENSION_NEXT_STEP,
            "action": self.action,
            "rationale": self.rationale,
            "pedagogy_eval_ref": self.pedagogy_eval_ref,
            "authority_required": self.authority_required,
        }


@dataclass(frozen=True)
class CandidateAbstention:
    """One dimension declined to propose, with a routable reason."""

    dimension: str
    reason: str
    detail: str = ""

    @property
    def route(self) -> str:
        return ABSTAIN_ROUTING.get(self.reason, "unknown")

    def to_dict(self) -> dict[str, object]:
        return {
            "dimension": self.dimension,
            "reason": self.reason,
            "detail": self.detail,
            "route": self.route,
        }


Proposal = ProposedUnderstanding | ProposedMisconception | ProposedNextStep


@dataclass(frozen=True)
class LearningClosureCandidate:
    """What we would propose writing; nothing more."""

    candidate_id: str
    goal_ref: str
    objective_ref: str
    proposals: tuple[Proposal, ...]
    abstentions: tuple[CandidateAbstention, ...]
    source_turn_ids: tuple[str, ...]
    pedagogy_eval_refs: tuple[str, ...]
    authority_requirements: tuple[str, ...]
    provenance: Mapping[str, object]
    semantic_fingerprint: str

    def understanding_proposals(self) -> tuple[ProposedUnderstanding, ...]:
        return tuple(
            item for item in self.proposals if isinstance(item, ProposedUnderstanding)
        )

    def misconception_proposals(self) -> tuple[ProposedMisconception, ...]:
        return tuple(
            item for item in self.proposals if isinstance(item, ProposedMisconception)
        )

    def next_step_proposals(self) -> tuple[ProposedNextStep, ...]:
        return tuple(
            item for item in self.proposals if isinstance(item, ProposedNextStep)
        )

    def abstentions_for(self, dimension: str) -> tuple[CandidateAbstention, ...]:
        return tuple(
            item for item in self.abstentions if item.dimension == dimension
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "goal_ref": self.goal_ref,
            "objective_ref": self.objective_ref,
            "proposals": [item.to_dict() for item in self.proposals],
            "abstentions": [item.to_dict() for item in self.abstentions],
            "source_turn_ids": list(self.source_turn_ids),
            "pedagogy_eval_refs": list(self.pedagogy_eval_refs),
            "authority_requirements": list(self.authority_requirements),
            "provenance": dict(self.provenance),
            "semantic_fingerprint": self.semantic_fingerprint,
        }


def semantic_fingerprint(
    *,
    goal_ref: str,
    objective_ref: str,
    proposals: Sequence[Proposal],
    abstentions: Sequence[CandidateAbstention],
    source_turn_ids: Sequence[str],
    pedagogy_eval_refs: Sequence[str],
    authority_requirements: Sequence[str],
) -> str:
    """Stable digest of the proposal content, deliberately excluding candidate_id.

    Re-assembling the same turn facts must yield the same fingerprint even though
    the proposal id is new, so a closure retry cannot silently submit the same
    proposal twice under a different identity.
    """
    return _canonical({
        "goal_ref": goal_ref,
        "objective_ref": objective_ref,
        "proposals": [item.to_dict() for item in proposals],
        "abstentions": [item.to_dict() for item in abstentions],
        "source_turn_ids": list(source_turn_ids),
        "pedagogy_eval_refs": list(pedagogy_eval_refs),
        "authority_requirements": list(authority_requirements),
    })


def find_forbidden_fields(value: Mapping[str, Any]) -> frozenset[str]:
    """Return any forbidden authority-shaped key present in a candidate payload."""
    return frozenset(key for key in value if key in FORBIDDEN_CANDIDATE_FIELDS)
