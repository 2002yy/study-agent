"""Run-scoped cancellation and hard-budget admission checks.

The repository owns cancellation truth; the live execution owner supplies the
current budget on every admission. Neither check mutates state or persists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.repositories.web_lookup_repository import WebLookupRepository


class ActiveResearchCancelled(RuntimeError):
    pass


class HardResearchBudgetReached(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ActiveResearchExecutionGuard:
    live: ActiveRuntimeLiveValues
    repository: WebLookupRepository
    run_id: str
    operation_id: str
    elapsed: Callable[[], float]

    def cancel_requested(self) -> bool:
        """Probe the current operation without changing the caller's exception type.

        The candidate pool raises ``CandidatePoolCancelled`` from its own
        boundary; the runtime's direct guard raises ``ActiveResearchCancelled``.
        Both must query the same repository operation on every check.
        """

        return bool(
            self.repository.cancel_requested(
                self.run_id, operation_id=self.operation_id
            )
        )

    def ensure_active(self) -> None:
        if self.cancel_requested():
            raise ActiveResearchCancelled("active research cancelled")

    def ensure_budget(self) -> None:
        """Sample the latest budget before the clock, without caching state."""
        hard_timeout_seconds = self.live.current_state().budget.hard_timeout_seconds
        if self.elapsed() >= hard_timeout_seconds:
            raise HardResearchBudgetReached
