"""Deterministic small-wave read scheduling for ranked research candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from math import isfinite
from typing import Any, Literal

from src.web.research.candidate_ranking import RankedCandidate
from src.web.research.contracts import ResearchBudget, ResearchClaim

ReadWaveStatus = Literal[
    "planned",
    "no_candidates",
    "context_deferred",
    "budget_exhausted",
    "conflict_reserve_held",
    "soft_deadline",
    "hard_deadline",
]
CancellationCheck = Callable[[], bool]


class ReadSchedulingCancelled(RuntimeError):
    """Raised when the owning turn requests cooperative cancellation."""


@dataclass(frozen=True)
class ReadSchedulerPolicy:
    critical_wave_size: int = 3
    major_wave_size: int = 2
    context_wave_size: int = 0
    conflict_reserve_fraction: float = 1 / 3
    allow_provenance_leads: bool = True


@dataclass(frozen=True)
class ReadWavePlan:
    claim_id: str
    status: ReadWaveStatus
    selected_candidate_ids: tuple[str, ...]
    selected_cluster_ids: tuple[str, ...]
    deferred_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    remaining_reads_before: int
    conflict_reserve_held: int
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "status": self.status,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "selected_cluster_ids": list(self.selected_cluster_ids),
            "deferred_candidate_ids": list(self.deferred_candidate_ids),
            "rejected_candidate_ids": list(self.rejected_candidate_ids),
            "remaining_reads_before": self.remaining_reads_before,
            "conflict_reserve_held": self.conflict_reserve_held,
            "reason_codes": list(self.reason_codes),
        }


Checkpoint = Callable[[ReadWavePlan], None]


def plan_read_wave(
    ranked: tuple[RankedCandidate, ...],
    *,
    claim: ResearchClaim,
    budget: ResearchBudget,
    policy: ReadSchedulerPolicy = ReadSchedulerPolicy(),
    conflict_open: bool = False,
    preserve_conflict_reserve: bool = True,
    should_cancel: CancellationCheck | None = None,
    checkpoint: Checkpoint | None = None,
) -> ReadWavePlan:
    """Select one cluster-diverse read wave without mutating budget truth."""

    _ensure_active(should_cancel)
    _validate_policy(policy)
    _validate_budget(budget)
    remaining = max(0, budget.max_reads - budget.reads_used)
    rejected = tuple(item.candidate.id for item in ranked if item.eligibility == "rejected")
    deferred = tuple(item.candidate.id for item in ranked if item.eligibility != "rejected")
    if budget.elapsed_seconds >= budget.hard_timeout_seconds:
        return _finish(_empty_plan(claim, "hard_deadline", remaining, deferred, rejected, ("hard_deadline_reached",)), should_cancel, checkpoint)
    if budget.elapsed_seconds >= budget.soft_timeout_seconds:
        return _finish(_empty_plan(claim, "soft_deadline", remaining, deferred, rejected, ("soft_deadline_reached",)), should_cancel, checkpoint)
    if remaining == 0:
        return _finish(_empty_plan(claim, "budget_exhausted", remaining, deferred, rejected, ("read_budget_exhausted",)), should_cancel, checkpoint)
    wave_size = {
        "critical": policy.critical_wave_size,
        "major": policy.major_wave_size,
        "context": policy.context_wave_size,
    }[claim.priority]
    if wave_size == 0:
        return _finish(_empty_plan(claim, "context_deferred", remaining, deferred, rejected, ("context_not_proactively_read",)), should_cancel, checkpoint)
    reserve = 0
    if preserve_conflict_reserve and not conflict_open:
        reserve = min(remaining, ceil(budget.max_reads * policy.conflict_reserve_fraction))
    available = max(0, remaining - reserve)
    if available == 0:
        return _finish(
            _empty_plan(claim, "conflict_reserve_held", remaining, deferred, rejected, ("read_budget_reserved_for_conflict",), reserve=reserve),
            should_cancel,
            checkpoint,
        )
    selected: list[RankedCandidate] = []
    selected_clusters: set[str] = set()
    for item in ranked:
        if len(selected) >= min(wave_size, available):
            break
        if not is_schedulable_candidate(item):
            continue
        cluster_id = item.assessment.cluster_id
        if cluster_id in selected_clusters:
            continue
        selected.append(item)
        selected_clusters.add(cluster_id)
    selected_ids = tuple(item.candidate.id for item in selected)
    deferred = tuple(
        item.candidate.id
        for item in ranked
        if item.candidate.id not in selected_ids and item.eligibility != "rejected"
    )
    status: ReadWaveStatus = "planned" if selected else "no_candidates"
    reasons = ("cluster_diverse_small_wave",) if selected else ("no_schedulable_candidates",)
    plan = ReadWavePlan(
        claim_id=claim.id,
        status=status,
        selected_candidate_ids=selected_ids,
        selected_cluster_ids=tuple(item.assessment.cluster_id for item in selected),
        deferred_candidate_ids=deferred,
        rejected_candidate_ids=rejected,
        remaining_reads_before=remaining,
        conflict_reserve_held=reserve,
        reason_codes=reasons,
    )
    return _finish(plan, should_cancel, checkpoint)


def is_schedulable_candidate(item: RankedCandidate) -> bool:
    """Shared eligibility predicate for every read-scheduling path (H9).

    Rejected candidates are never schedulable; lead_only candidates are only
    schedulable when they carry a provenance-grade gain signal. Both
    plan_read_wave (fresh candidates) and the reusable-candidate binding in
    the fair read plan must use this one predicate so the two paths cannot
    drift apart again.
    """
    if item.eligibility == "rejected":
        return False
    if (
        item.eligibility == "lead_only"
        and not _LEAD_SCHEDULABLE_SIGNALS.intersection(item.assessment.expected_gain_signals)
    ):
        return False
    return True


_LEAD_SCHEDULABLE_SIGNALS = {
    "new_primary",
    "new_provenance_lead",
    "new_contradiction",
}

# Lead discovery is a separate, deterministic scheduling path (v1). It does not
# reuse the evidence-gain signals above: `new_provenance_lead` is an *Evidence*
# stage gain (lead links on Gate-eligible evidence), while lead discovery is a
# *Discovery* stage action. Lead reads never produce eligible evidence.
LEAD_DISCOVERY_INTENTS = frozenset({"primary", "provenance", "verification"})


def is_schedulable_lead(
    item: RankedCandidate,
    *,
    lead_budget_available: bool,
    gap_needs_primary: bool,
) -> bool:
    """Deterministic v1 lead-scheduling rule.

    A candidate is schedulable as a lead when all of these hold:
    - it is ``lead_only`` (``rejected`` is never read; ``eligible`` goes to an
      evidence read instead);
    - its query intents include a primary/provenance/verification intent;
    - the open gap still lacks the corresponding primary/provenance evidence;
    - a bounded lead-read budget is still available.

    No model prediction is required: the assessor already performed the
    important filter (``off_target`` -> ``rejected``).
    """

    if item.eligibility != "lead_only":
        return False
    if not lead_budget_available or not gap_needs_primary:
        return False
    return bool(LEAD_DISCOVERY_INTENTS.intersection(item.candidate.intents))


def _lead_is_schedulable(item: RankedCandidate, policy: ReadSchedulerPolicy) -> bool:
    if not policy.allow_provenance_leads:
        return False
    return bool(
        _LEAD_SCHEDULABLE_SIGNALS
        & set(item.assessment.expected_gain_signals)
    )


def _empty_plan(
    claim: ResearchClaim,
    status: ReadWaveStatus,
    remaining: int,
    deferred: tuple[str, ...],
    rejected: tuple[str, ...],
    reasons: tuple[str, ...],
    *,
    reserve: int = 0,
) -> ReadWavePlan:
    return ReadWavePlan(
        claim_id=claim.id,
        status=status,
        selected_candidate_ids=(),
        selected_cluster_ids=(),
        deferred_candidate_ids=deferred,
        rejected_candidate_ids=rejected,
        remaining_reads_before=remaining,
        conflict_reserve_held=reserve,
        reason_codes=reasons,
    )


def _finish(
    plan: ReadWavePlan,
    should_cancel: CancellationCheck | None,
    checkpoint: Checkpoint | None,
) -> ReadWavePlan:
    _ensure_active(should_cancel)
    if checkpoint is not None:
        checkpoint(plan)
    return plan


def _ensure_active(check: CancellationCheck | None) -> None:
    if check is not None and check():
        raise ReadSchedulingCancelled("read scheduling cancelled")


def _validate_policy(policy: ReadSchedulerPolicy) -> None:
    if min(policy.critical_wave_size, policy.major_wave_size, policy.context_wave_size) < 0:
        raise ValueError("read wave sizes cannot be negative")
    if not 0.0 <= policy.conflict_reserve_fraction < 1.0:
        raise ValueError("conflict_reserve_fraction must be in [0, 1)")


def _validate_budget(budget: ResearchBudget) -> None:
    if budget.max_reads < 0 or not 0 <= budget.reads_used <= budget.max_reads:
        raise ValueError("invalid read budget usage")
    if not isfinite(budget.soft_timeout_seconds) or budget.soft_timeout_seconds <= 0:
        raise ValueError("soft timeout must be positive")
    if not isfinite(budget.hard_timeout_seconds) or budget.hard_timeout_seconds < budget.soft_timeout_seconds:
        raise ValueError("hard timeout cannot precede soft timeout")
    if not isfinite(budget.elapsed_seconds) or budget.elapsed_seconds < 0:
        raise ValueError("elapsed time cannot be negative")


__all__ = [
    "LEAD_DISCOVERY_INTENTS",
    "ReadSchedulerPolicy",
    "ReadSchedulingCancelled",
    "ReadWavePlan",
    "ReadWaveStatus",
    "is_schedulable_candidate",
    "is_schedulable_lead",
    "plan_read_wave",
]
