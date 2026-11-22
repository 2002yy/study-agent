"""Run one admitted candidate through the existing reader chain.

The research executor still owns recovery, budgets, durable attempts, source
records, checkpoints and publication.  This context only binds stable run
dependencies and returns the actual chain steps for the caller to account for.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_read_scheduling import ActiveReadDispatchContext
from src.application.research_runtime_read_site import (
    ActiveReadSiteContext,
    specialist_chain_run,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainRun, ChainStepResult
from src.web.research.health_breaker import host_of


@dataclass(frozen=True, slots=True)
class ActiveReadExecutionContext:
    """Stable backend wiring; dispatch owns the shared live context and history."""

    gateway: Any
    gateway_read: Callable[..., Mapping[str, Any]]
    hard_seconds_left: Callable[[], float]
    dispatch: ActiveReadDispatchContext
    read_site: ActiveReadSiteContext
    executor_factory: Callable[..., dict[str, Any]]
    chain_runner: Callable[..., ChainRun]

    def run_candidate(
        self,
        *,
        candidate: CandidatePoolItem,
        source_limit: int,
        outer_attempt_number: int,
    ) -> tuple[ChainRun, list[ChainStepResult]]:
        """Try the explicit specialist first, then the unchanged default chain.

        Results are not stored here. Read-site diagnostics use the current
        run context; backend selection re-reads history at dispatch time.
        """

        specialist_step = self.read_site.try_specialist(
            self.dispatch.live.current_context(), candidate, source_limit
        )
        chain_steps: list[ChainStepResult] = []
        if specialist_step is not None:
            chain_steps = [specialist_step]
            chain_run = specialist_chain_run(
                candidate_id=candidate.id,
                step=specialist_step,
                outer_attempt_number=outer_attempt_number,
            )
        else:
            escalation_backend = (
                self.gateway.escalation_backend()
                if hasattr(self.gateway, "escalation_backend")
                else None
            )
            executors = self.executor_factory(
                source_limit=source_limit,
                gateway_read=self.gateway_read,
                escalation_backend=escalation_backend,
                hard_seconds_left=self.hard_seconds_left,
            )
            chain_run = self.chain_runner(
                candidate_id=candidate.id,
                url=candidate.url,
                host=host_of(candidate.url),
                outer_attempt_number=outer_attempt_number,
                chain=self.dispatch.available_backends,
                executors=executors,
                record_outcome=chain_steps.append,
                attempted_backends=self.dispatch.attempted_backends(
                    candidate_id=candidate.id
                ),
                health_state_for=self.dispatch.health_state_for,
            )
        return chain_run, chain_steps
