"""Run-scoped read observation hooks bound to the live research snapshot.

The read gateway owns retry and escalation semantics. This context only
exposes the phase/diagnostic callbacks it needs. It reads the current context
and cursor for each observation, because a checkpoint can replace both during
one active execution; it never owns either mutable value or a checkpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import RuntimePhaseTiming, TimingLedger


@dataclass(frozen=True, slots=True)
class ActiveReadObservationContext:
    current_context: Callable[[], dict[str, Any]]
    current_cursor: Callable[[], ResearchRuntimeCursor]
    phase_timing: RuntimePhaseTiming
    timing_ledger: TimingLedger

    def wave_index(self) -> int:
        return int(self.current_cursor().wave_index)

    def phase_start(self, phase: str) -> None:
        self.phase_timing.begin(phase)

    def phase_end(self, phase: str) -> None:
        # Do not hold the context seen at start: checkpoint recovery may have
        # replaced it before this finally callback is invoked.
        self.phase_timing.end(phase, context=self.current_context())

    def retry(self, *, wait_ms: float, fetch_ms: float) -> None:
        self.timing_ledger.record_retry(wait_ms=wait_ms, fetch_ms=fetch_ms)
