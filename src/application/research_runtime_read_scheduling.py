"""Pre-attempt read scheduling with explicit, current run inputs.

Scheduling decides whether a candidate can start a reader chain.  It neither
executes a read nor changes durable outcomes, model budgets, or checkpoints.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_read_scheduling_observation import (
    record_read_scheduling_decision,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.health_breaker import PerRunBreaker, host_of
from src.web.research.progressive_routing import (
    SchedulingContext,
    SchedulingDecision,
    schedulable_now,
)
from src.web.research.runtime import RuntimeReadOutcome
from src.web.research.scheduler import attempted_read_backends


@dataclass(frozen=True, slots=True)
class ActiveReadDispatchContext:
    """One run's stable reader dependencies, never its rebound cursor/context.

    Scheduling and the subsequent reader chain must both consult the current
    candidate-local attempt history.  A checkpoint or resumed run may replace
    the cursor and research context between those two operations.
    """

    breaker: PerRunBreaker | None
    available_backends: tuple[str, ...]
    research_seconds_left: Callable[[], float]

    def schedule(
        self,
        *,
        candidate: CandidatePoolItem,
        read_outcomes: Sequence[RuntimeReadOutcome],
        context: dict[str, Any],
    ) -> SchedulingDecision:
        decision = schedule_active_research_read(
            candidate_id=str(candidate.id),
            url=candidate.url,
            read_outcomes=read_outcomes,
            breaker=self.breaker,
            available_backends=self.available_backends,
            research_seconds_left=self.research_seconds_left,
        )
        # Observation follows admission, with the caller's current context.
        record_read_scheduling_decision(context, decision)
        return decision

    def attempted_backends(
        self, *, candidate_id: str, read_outcomes: Sequence[RuntimeReadOutcome]
    ) -> tuple[str, ...]:
        """Re-read the live outcome list when dispatching, after admission."""

        return attempted_read_backends(read_outcomes, candidate_id)

    def health_state_for(self, backend: str, host: str) -> str:
        if self.breaker is None:
            return ""
        return self.breaker.state_for(backend=backend, host=host)


def schedule_active_research_read(
    *,
    candidate_id: str,
    url: str,
    read_outcomes: Sequence[RuntimeReadOutcome],
    breaker: PerRunBreaker | None,
    available_backends: tuple[str, ...],
    research_seconds_left: Callable[[], float],
) -> SchedulingDecision:
    """Decide admission from explicit inputs, without writing diagnostics.

    The remaining-time callback is evaluated *after* collecting the candidate's
    attempt history, at the same point as in the previous executor closure.
    The dispatch context records this decision after the scheduler returns.
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
    return decision
