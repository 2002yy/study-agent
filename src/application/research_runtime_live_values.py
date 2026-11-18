"""Current mutable values owned by one active research execution.

The state is a replaceable value: checkpoint preparation, model planning,
steering and evidence projection may each produce a *new* ResearchState.
The owner persists for the whole execution, so callbacks can read its current
value after a recovery or checkpoint rebind instead of holding a stale state.

State and cursor are replaceable values with a shared execution lifetime.
Persisted context remains an executor local until its separate migration;
never mirror that mutable dictionary into this owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor


@dataclass(slots=True)
class ActiveRuntimeLiveValues:
    state: ResearchState
    cursor: ResearchRuntimeCursor = field(default_factory=ResearchRuntimeCursor)

    def current_state(self) -> ResearchState:
        """Observe the latest state, including a checkpoint/recovery rebind."""

        return self.state

    def current_cursor(self) -> ResearchRuntimeCursor:
        """Observe the latest cursor after an audit or wave handoff replaces it."""

        return self.cursor

    def set_cursor(self, cursor: ResearchRuntimeCursor) -> None:
        self.cursor = cursor

    def hard_timeout_seconds(self) -> float:
        """Budget clock reads the same live state as model admission."""

        return self.state.budget.hard_timeout_seconds
