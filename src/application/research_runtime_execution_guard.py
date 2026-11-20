"""Run-scoped cancellation and hard-budget admission checks.

The repository owns cancellation truth; the active executor supplies the live
budget state. Neither check mutates state or persists a checkpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState


class ActiveResearchCancelled(RuntimeError):
    pass


class HardResearchBudgetReached(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ActiveResearchExecutionGuard:
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

    def ensure_budget(self, state: ResearchState) -> None:
        if self.elapsed() >= state.budget.hard_timeout_seconds:
            raise HardResearchBudgetReached
