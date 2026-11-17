"""Run-scoped elapsed time and research/model timeout calculations.

The executor owns budget mutations and cost settlement. This clock samples
time only on demand and reads the *current* hard limit after state recovery or
rebinding; it never persists or changes the budget.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResearchBudgetClock:
    monotonic: Callable[[], float]
    execution_started: float
    base_elapsed: float
    current_hard_seconds: Callable[[], float]
    model_timeout_cap_seconds: float
    reserve_seconds: float

    def elapsed(self) -> float:
        return self.base_elapsed + max(0.0, self.monotonic() - self.execution_started)

    def elapsed_ms(self) -> float:
        """Diagnostic reading; each call samples the clock once."""

        return round(self.elapsed() * 1000.0, 1)

    def hard_seconds_left(self) -> float:
        return self.current_hard_seconds() - self.elapsed()

    def research_seconds_left(self) -> float:
        """Keep the finalization reserve outside the search/read window."""

        return self.current_hard_seconds() - self.reserve_seconds - self.elapsed()

    def research_window_exhausted(self) -> bool:
        """Check the live research window with one elapsed-time sample."""

        return self.research_seconds_left() <= 0.0

    def remaining_timeout(self) -> float:
        """Keep the historical one-second floor and per-call model cap."""

        return max(
            1.0, min(self.model_timeout_cap_seconds, self.research_seconds_left())
        )
