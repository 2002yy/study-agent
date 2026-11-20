"""Run-bound reader-attempt test setup shared by transition and telemetry tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.application.research_runtime_read_attempt_context import ActiveReadAttemptContext
from src.web.research.runtime import ResearchRuntimeCursor


def read_attempt_recorder(
    *,
    breaker: Any = None,
    run_id: str = "test-run",
    utc_now: Callable[[], str] = lambda: "started",
    on_cursor_change: Callable[[ResearchRuntimeCursor], None] = lambda _cursor: None,
    research_seconds_left: Callable[[], float] = lambda: 10.0,
    elapsed: Callable[[], float] = lambda: 1.0,
    escalation_recorder: Callable[..., None] | None = None,
) -> ActiveReadAttemptContext:
    kwargs: dict[str, Any] = {}
    if escalation_recorder is not None:
        kwargs["escalation_recorder"] = escalation_recorder
    return ActiveReadAttemptContext(
        breaker=breaker,
        run_id=run_id,
        utc_now=utc_now,
        on_cursor_change=on_cursor_change,
        research_seconds_left=research_seconds_left,
        elapsed=elapsed,
        **kwargs,
    )
