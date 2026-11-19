"""Run-scoped model attempt callbacks with explicit mutable-cursor access.

The executor owns the real cursor and checkpoint implementation. This context
only binds their callbacks and preserves the frozen before/after-call order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from src.web.research.contracts import ResearchState
from src.web.research.model_gateway import (
    ResearchModelAttemptStart,
    ResearchModelCallAudit,
)
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    _model_attempt_start,
    begin_model_attempt,
    finish_model_attempt,
)


class LiveModelAttemptValues(Protocol):
    """Only the live state and cursor capabilities needed by model auditing."""

    def current_state(self) -> ResearchState: ...

    def current_cursor(self) -> ResearchRuntimeCursor: ...

    def set_cursor(self, cursor: ResearchRuntimeCursor) -> None: ...


@dataclass(frozen=True, slots=True)
class ActiveModelAttemptContext:
    """Keep model attempt order without retaining stale cursor or budget state."""

    current_state: Callable[[], ResearchState]
    current_cursor: Callable[[], ResearchRuntimeCursor]
    set_cursor: Callable[[ResearchRuntimeCursor], None]
    ensure_active: Callable[[], None]
    ensure_budget: Callable[[ResearchState], None]
    checkpoint: Callable[[], Any]

    @classmethod
    def for_live_values(
        cls,
        live: LiveModelAttemptValues,
        *,
        ensure_active: Callable[[], None],
        ensure_budget: Callable[[ResearchState], None],
        checkpoint: Callable[[], Any],
    ) -> ActiveModelAttemptContext:
        """Observe rebound state/cursor through one explicit per-run owner."""

        return cls(
            current_state=live.current_state,
            current_cursor=live.current_cursor,
            set_cursor=live.set_cursor,
            ensure_active=ensure_active,
            ensure_budget=ensure_budget,
            checkpoint=checkpoint,
        )

    def next_attempt_number(self, logical_call_id: str) -> int:
        """Admit from the latest recovered cursor, before any physical model I/O.

        Recovery may add an interrupted attempt or a completed audit after
        this context was created. Keep the existing two-attempt ceiling and
        leave budget checks and persistence to the ``started`` callback.
        """

        return _model_attempt_start(self.current_cursor(), logical_call_id)

    def started(self, marker: ResearchModelAttemptStart) -> None:
        """Persist inflight *before* the model gateway can reserve and send."""

        self.ensure_active()
        self.ensure_budget(self.current_state())
        self.set_cursor(begin_model_attempt(self.current_cursor(), marker))
        self.checkpoint()

    def finished(self, audit: ResearchModelCallAudit) -> None:
        """Finish in memory; the semantic-result checkpoint remains the owner."""

        self.set_cursor(finish_model_attempt(self.current_cursor(), audit))
        self.ensure_active()
