from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class TaskEvent:
    """Portable event emitted by service-layer tasks."""

    task_name: str
    event_type: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0


TaskEventCallback = Callable[[TaskEvent], None]


def elapsed_ms_since(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def emit_task_event(
    callback: TaskEventCallback | None,
    task_name: str,
    event_type: str,
    *,
    message: str = "",
    data: dict[str, Any] | None = None,
    started_at: float | None = None,
) -> None:
    if callback is None:
        return
    elapsed_ms = elapsed_ms_since(started_at) if started_at is not None else 0
    callback(
        TaskEvent(
            task_name=task_name,
            event_type=event_type,
            message=message,
            data=data or {},
            elapsed_ms=elapsed_ms,
        )
    )
