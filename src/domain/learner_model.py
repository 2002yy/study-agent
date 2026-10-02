"""Read-only learner-model projection contracts.

These values are derived on demand. They do not own mastery, evaluation, or
memory truth and therefore deliberately contain no generated identity or
timestamp fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LearnerClaimState:
    claim_id: str
    revision_id: str
    claim_kind: str
    understanding_status: str
    validation_result: str


@dataclass(frozen=True)
class LearnerEvaluationSummary:
    run_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    review_required_count: int = 0
    protocols: tuple[str, ...] = ()
    evaluator_versions: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfirmedLearnerPreference:
    category: str
    value: str


@dataclass(frozen=True)
class LearnerModelSnapshot:
    """Bounded projection from existing truth owners, never a write model."""

    thread_id: str
    source: str = "derived_read_only"
    goal_id: str = ""
    topic_id: str = ""
    objective: str = ""
    goal_status: str = ""
    claim_states: tuple[LearnerClaimState, ...] = ()
    unresolved_count: int = 0
    # 165-B: primary durable NextStep, exposed read-only. Additive: empty when absent,
    # so nothing that ignores it changes behaviour.
    next_step_id: str = ""
    next_step_text: str = ""
    next_step_status: str = ""
    evaluation: LearnerEvaluationSummary = LearnerEvaluationSummary()
    confirmed_profile: tuple[ConfirmedLearnerPreference, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
