"""Deterministic phase-budget admission for the active research runtime.

RQ1-C Phase Budget & Scheduling: the runtime now has many *legitimate* next
actions (evidence reads, evidence-stage lead follow-ups, candidate-lead
discovery), but a bounded run cannot afford all of them. This module answers one
question, deterministically and before the action starts:

    can the remaining budget afford this action's COMPLETE chain?

"Complete chain" matters: an evidence-lead hint follow-up is not "one search" -
it is ``follow-up query -> provider search -> candidate assessment ->
scheduling -> read -> extraction -> Gate recompute``. Starting it with too
little budget is what starved finalization and dropped reviewable answers.

Frozen boundaries (never touched by this module):
- Evidence Gate, assessor, query hardening, provider resilience, Lead contracts.
- The qualification thresholds (45s soft / 60s hard, 8 reads / 8 model calls).

Cost values here are conservative deterministic estimates. They are recorded per
action (``estimated_seconds`` / ``required_reads`` / ``required_model_calls``)
so a later round can calibrate them from action-level observability instead of
guessing from total elapsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ActionType = Literal[
    "evidence_read",
    "conflict_read",
    "evidence_lead_direct_url",
    "evidence_lead_trusted_domain",
    "evidence_lead_hint_query",
    "candidate_lead",
]

# Priority ladder (user-frozen for this batch): a lower rank is strictly more
# valuable. The scheduler may only spend the *tail* of a run on higher ranks.
ACTION_PRIORITY: dict[ActionType, int] = {
    "evidence_read": 0,
    "conflict_read": 1,
    "evidence_lead_direct_url": 2,
    "evidence_lead_trusted_domain": 3,
    "evidence_lead_hint_query": 4,
    "candidate_lead": 5,
}

# Full-chain cost estimates (deterministic v1). Action chains differ:
# - evidence_read:            read + extraction model call
# - conflict_read:            same as evidence_read (forced onto a conflict claim)
# - evidence_lead_direct_url: candidate already known -> read + extraction
# - *_trusted_domain / hint:  search + assessment + read + extraction
ACTION_COST_SECONDS: dict[ActionType, float] = {
    "evidence_read": 10.0,
    "conflict_read": 10.0,
    "evidence_lead_direct_url": 10.0,
    "evidence_lead_trusted_domain": 28.0,
    "evidence_lead_hint_query": 28.0,
    "candidate_lead": 24.0,
}

ACTION_REQUIRED_READS: dict[ActionType, int] = {
    "evidence_read": 1,
    "conflict_read": 1,
    "evidence_lead_direct_url": 1,
    "evidence_lead_trusted_domain": 1,
    "evidence_lead_hint_query": 1,
    "candidate_lead": 1,
}

ACTION_REQUIRED_MODEL_CALLS: dict[ActionType, int] = {
    "evidence_read": 1,
    "conflict_read": 1,
    "evidence_lead_direct_url": 1,
    # assessment + extraction
    "evidence_lead_trusted_domain": 2,
    "evidence_lead_hint_query": 2,
    # assessment + extraction (discovery read may add a lead-discovery call)
    "candidate_lead": 2,
}

# Tail of a run that belongs to finalization: Gate, answer synthesis, answer
# binding/auditing, serialization. No new discovery branch may start inside it.
FINALIZATION_RESERVE_SECONDS = 12.0

# Research model-call budget of a bounded run. The frozen qualification contract
# is 8 model calls total with 2 reserved for the answer stage (generation +
# claim binding), so the research phase may spend at most 6.
PHASE_RESEARCH_MODEL_CALL_BUDGET = 6

# Inside the soft deadline the runtime stops low-yield expansion: only P0/P1 and
# high-confidence P2 (a direct deeper URL that is already known) are admitted.
EVIDENCE_LEAD_DIRECT_URL_MAX_PRIORITY = ACTION_PRIORITY["evidence_lead_direct_url"]


@dataclass(frozen=True)
class PhaseBudget:
    """Remaining budget of one bounded run, in all three dimensions."""

    elapsed_seconds: float
    soft_timeout_seconds: float
    hard_timeout_seconds: float
    remaining_reads: int
    remaining_model_calls: int
    finalization_reserve_seconds: float = FINALIZATION_RESERVE_SECONDS

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.hard_timeout_seconds - self.elapsed_seconds)

    @property
    def research_seconds(self) -> float:
        return max(0.0, self.remaining_seconds - self.finalization_reserve_seconds)

    @property
    def in_finalization_reserve(self) -> bool:
        return self.remaining_seconds <= self.finalization_reserve_seconds

    @property
    def past_soft_deadline(self) -> bool:
        return self.elapsed_seconds >= self.soft_timeout_seconds


@dataclass(frozen=True)
class PhaseAdmission:
    admitted: bool
    reason: str
    priority: int
    estimated_seconds: float
    required_reads: int
    required_model_calls: int

    def to_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "reason": self.reason,
            "priority": self.priority,
            "estimated_seconds": self.estimated_seconds,
            "required_reads": self.required_reads,
            "required_model_calls": self.required_model_calls,
        }


def admit_phase_action(
    budget: PhaseBudget,
    *,
    action_type: ActionType,
    estimated_seconds: float | None = None,
    required_reads: int | None = None,
    required_model_calls: int | None = None,
) -> PhaseAdmission:
    """Deterministic admission for one expensive research action.

    Checks, in order: finalization reserve -> soft-deadline priority gate ->
    full-chain wall clock -> read budget -> model-call budget.
    """

    priority = ACTION_PRIORITY[action_type]
    seconds = (
        ACTION_COST_SECONDS[action_type]
        if estimated_seconds is None
        else float(estimated_seconds)
    )
    reads = (
        ACTION_REQUIRED_READS[action_type]
        if required_reads is None
        else int(required_reads)
    )
    calls = (
        ACTION_REQUIRED_MODEL_CALLS[action_type]
        if required_model_calls is None
        else int(required_model_calls)
    )

    def _result(admitted: bool, reason: str) -> PhaseAdmission:
        return PhaseAdmission(
            admitted=admitted,
            reason=reason,
            priority=priority,
            estimated_seconds=seconds,
            required_reads=reads,
            required_model_calls=calls,
        )

    if budget.in_finalization_reserve:
        return _result(False, "finalization_reserve")
    if budget.past_soft_deadline and priority > EVIDENCE_LEAD_DIRECT_URL_MAX_PRIORITY:
        # Past the soft deadline only P0/P1 and an already-known direct deeper
        # URL may run; generic hint queries and candidate-lead discovery stop.
        return _result(False, "past_soft_deadline")
    if budget.research_seconds < seconds:
        return _result(False, "skipped_insufficient_phase_budget")
    if budget.remaining_reads < reads:
        return _result(False, "insufficient_read_budget")
    if budget.remaining_model_calls < calls:
        return _result(False, "insufficient_model_budget")
    return _result(True, "admitted")


__all__ = [
    "ACTION_COST_SECONDS",
    "ACTION_PRIORITY",
    "ACTION_REQUIRED_MODEL_CALLS",
    "ACTION_REQUIRED_READS",
    "ActionType",
    "EVIDENCE_LEAD_DIRECT_URL_MAX_PRIORITY",
    "FINALIZATION_RESERVE_SECONDS",
    "PHASE_RESEARCH_MODEL_CALL_BUDGET",
    "PhaseAdmission",
    "PhaseBudget",
    "admit_phase_action",
]
