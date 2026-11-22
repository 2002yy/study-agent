"""Run-scoped phase and read observation bound to the live research snapshot.

The gateway still owns retry and escalation semantics. This context binds
phase timing, retry timing and wave-index observations to the same live run,
so no caller needs to capture a mutable research context in a timing closure.
Each observation reads the current context/cursor because a checkpoint can
replace either; this context never owns that state or a checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import RuntimePhaseTiming, TimingLedger


@dataclass(frozen=True, slots=True)
class ActiveRuntimeObservationContext:
    live: ActiveRuntimeLiveValues
    phase_timing: RuntimePhaseTiming
    timing_ledger: TimingLedger

    def current_context(self) -> dict[str, Any]:
        """Expose the current context to the existing read gateway callback."""
        return self.live.current_context()

    def current_cursor(self) -> ResearchRuntimeCursor:
        """Resolve the cursor after checkpoint recovery or wave handoff."""
        return self.live.current_cursor()

    def wave_index(self) -> int:
        return int(self.current_cursor().wave_index)

    def phase_start(self, phase: str) -> None:
        self.phase_timing.begin(phase)

    def phase_end(self, phase: str) -> None:
        # A checkpoint may have rebound the context since phase_start, even
        # for assessment/late-tail phases outside the read gateway.
        self.phase_timing.end(phase, context=self.current_context())

    def retry(self, *, wait_ms: float, fetch_ms: float) -> None:
        self.timing_ledger.record_retry(wait_ms=wait_ms, fetch_ms=fetch_ms)
