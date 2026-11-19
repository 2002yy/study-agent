"""Project wave read charges onto the current research budget.

The per-wave quota owns only read/character charges. The executor still owns
ResearchState and checkpoint persistence; this context merely binds the live
state/cursor, quota and clock used by all three read paths (Deep seeds,
physical evidence reads and lead discovery).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from src.application.research_runtime_checkpoint import updated_runtime_budget
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_quota_context import ReadWaveQuotaContext
from src.web.research.contracts import ResearchState


@dataclass(frozen=True, slots=True)
class ReadWaveBudgetContext:
    live: ActiveRuntimeLiveValues
    quota: ReadWaveQuotaContext
    elapsed: Callable[[], float]

    def project(self) -> ResearchState:
        """Return a new state using the latest cursor/state and shared charges.

        This does not update the owner, write diagnostics or checkpoint. Each
        caller keeps its original ordering around those operations.
        """

        return updated_runtime_budget(
            self.live.current_state(),
            self.live.current_cursor(),
            elapsed_seconds=self.elapsed(),
            reads_used=self.quota.successful_reads,
        )
