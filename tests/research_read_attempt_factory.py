"""One shared live reader-attempt fixture for transition and telemetry tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.application.research_runtime_read_attempt_context import ActiveReadAttemptContext
from src.web.research.runtime import ResearchRuntimeCursor


@dataclass(slots=True)
class RecordingReadLive:
    """Record cursor transitions while modeling a replaceable runtime context."""

    cursor: ResearchRuntimeCursor = field(default_factory=ResearchRuntimeCursor)
    context: dict[str, Any] = field(default_factory=dict)
    published: list[ResearchRuntimeCursor] = field(default_factory=list)

    def current_cursor(self) -> ResearchRuntimeCursor:
        return self.cursor

    def current_context(self) -> dict[str, Any]:
        return self.context

    def set_cursor(self, cursor: ResearchRuntimeCursor) -> None:
        self.cursor = cursor
        self.published.append(cursor)


def read_attempt_recorder(
    *,
    live: RecordingReadLive | None = None,
    breaker: Any = None,
    run_id: str = "test-run",
    utc_now: Callable[[], str] = lambda: "started",
    research_seconds_left: Callable[[], float] = lambda: 10.0,
    elapsed: Callable[[], float] = lambda: 1.0,
    escalation_recorder: Callable[..., None] | None = None,
) -> ActiveReadAttemptContext:
    kwargs: dict[str, Any] = {}
    if escalation_recorder is not None:
        kwargs["escalation_recorder"] = escalation_recorder
    return ActiveReadAttemptContext(
        live=live if live is not None else RecordingReadLive(),
        breaker=breaker,
        run_id=run_id,
        utc_now=utc_now,
        research_seconds_left=research_seconds_left,
        elapsed=elapsed,
        **kwargs,
    )
