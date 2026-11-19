"""Current mutable values owned by one active research execution.

The state is a replaceable value: checkpoint preparation, model planning,
steering and evidence projection may each produce a *new* ResearchState.
The owner persists for the whole execution, so callbacks can read its current
value after a recovery or checkpoint rebind instead of holding a stale state.

State, cursor and persisted context share an execution lifetime. Each can be
replaced by checkpoint, recovery, steering or wave settlement; readers must
resolve the latest value from this owner instead of capturing an old dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor


@dataclass(slots=True)
class ActiveRuntimeLiveValues:
    state: ResearchState
    cursor: ResearchRuntimeCursor = field(default_factory=ResearchRuntimeCursor)
    context: dict[str, Any] = field(default_factory=dict)

    def current_state(self) -> ResearchState:
        """Observe the latest state, including a checkpoint/recovery rebind."""

        return self.state

    def current_cursor(self) -> ResearchRuntimeCursor:
        """Observe the latest cursor after an audit or wave handoff replaces it."""

        return self.cursor

    def set_cursor(self, cursor: ResearchRuntimeCursor) -> None:
        self.cursor = cursor

    def current_context(self) -> dict[str, Any]:
        """Observe the latest durable research context after a rebind."""

        return self.context

    def hard_timeout_seconds(self) -> float:
        """Budget clock reads the same live state as model admission."""

        return self.state.budget.hard_timeout_seconds
