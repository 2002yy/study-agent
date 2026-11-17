"""Pre-attempt read scheduling with explicit, current run inputs.

Scheduling decides whether a candidate can start a reader chain.  It neither
executes a read nor changes durable outcomes, model budgets, or checkpoints.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from src.web.research.health_breaker import PerRunBreaker, host_of
from src.web.research.progressive_routing import (
    SchedulingContext,
    SchedulingDecision,
    schedulable_now,
)
from src.web.research.runtime import RuntimeReadOutcome
from src.web.research.scheduler import attempted_read_backends
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def schedule_active_research_read(
    *,
    candidate_id: str,
    url: str,
    read_outcomes: Sequence[RuntimeReadOutcome],
    context: dict[str, Any],
    breaker: PerRunBreaker | None,
    available_backends: tuple[str, ...],
    research_seconds_left: Callable[[], float],
) -> SchedulingDecision:
    """Preserve candidate-local attempts and bounded scheduling diagnostics.

    The remaining-time callback is evaluated *after* collecting the candidate's
    attempt history, at the same point as in the previous executor closure.
    """

    attempted = attempted_read_backends(read_outcomes, candidate_id)
    decision = schedulable_now(
        SchedulingContext(
            candidate_id=str(candidate_id),
            available_backends=available_backends,
            attempted_backends=attempted,
            host=host_of(url),
            remaining_seconds=research_seconds_left(),
        ),
        health_state_for=(
            (lambda backend, host: breaker.state_for(backend=backend, host=host))
            if breaker is not None
            else None
        ),
    )
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        entries = metrics.get("read_scheduling")
        if not isinstance(entries, list):
            entries = []
        entries.append(decision.to_dict())
        metrics["read_scheduling"] = entries[-60:]
    return decision
