"""Thread-level summary lifecycle state."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.runtime_entities import utc_now


@dataclass(frozen=True)
class ThreadSummaryState:
    thread_id: str
    status: str = "not_summarized"
    source_thread_version: int | None = None
    last_completed_turn_id: str | None = None
    current_last_completed_turn_id: str | None = None
    closure_run_id: str | None = None
    summarized_at: str | None = None
    updated_at: str = field(default_factory=utc_now)
    version: int = 1

    @property
    def can_summarize(self) -> bool:
        return bool(
            self.current_last_completed_turn_id
            and self.status != "summarized"
        )
