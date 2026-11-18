"""Run-scoped model attempt callbacks with explicit mutable-cursor access.

The executor owns the real cursor and checkpoint implementation. This context
only binds their callbacks and preserves the frozen before/after-call order.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.web.research.contracts import ResearchState
from src.web.research.model_gateway import (
    ResearchModelAttemptStart,
    ResearchModelCallAudit,
)
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    begin_model_attempt,
    finish_model_attempt,
)


@dataclass(frozen=True, slots=True)
class ActiveModelAttemptContext:
    """Keep model attempt order without retaining stale cursor or budget state."""

    current_state: Callable[[], ResearchState]
    current_cursor: Callable[[], ResearchRuntimeCursor]
    set_cursor: Callable[[ResearchRuntimeCursor], None]
    ensure_active: Callable[[], None]
    ensure_budget: Callable[[ResearchState], None]
    checkpoint: Callable[[], Any]

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
