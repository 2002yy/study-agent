"""Current mutable values owned by one active research execution.

The state is a replaceable value: checkpoint preparation, model planning,
steering and evidence projection may each produce a *new* ResearchState.
The owner persists for the whole execution, so callbacks can read its current
value after a recovery or checkpoint rebind instead of holding a stale state.

This first migration owns only ``state``. Cursor and persisted context remain
the executor's local variables until their independent contracts are migrated.
Do not mirror either into this object before their single ownership is moved.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.web.research.contracts import ResearchState


@dataclass(slots=True)
class ActiveRuntimeLiveValues:
    state: ResearchState

    def current_state(self) -> ResearchState:
        """Observe the latest state, including a checkpoint/recovery rebind."""

        return self.state

    def hard_timeout_seconds(self) -> float:
        """Budget clock reads the same live state as model admission."""

        return self.state.budget.hard_timeout_seconds
