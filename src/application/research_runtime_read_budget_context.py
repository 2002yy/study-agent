"""Project wave read charges onto the current research budget.

The per-wave quota owns only read/character charges. The executor still owns
ResearchState and checkpoint persistence. This context is the single view of
live budget limits and accumulated quota for Deep seeds, evidence reads and
lead discovery; it never authorizes a physical read or performs persistence.
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

    def exhausted(self) -> bool:
        """Check the shared read/character quota against the latest live limits."""
        limits = self.live.current_state().budget
        return self.quota.exhausted(
            max_reads=limits.max_reads,
            max_total_chars=limits.max_total_chars,
        )

    def remaining_chars(self) -> int:
        """Deep materialization reads the current character ceiling."""
        return self.quota.remaining_chars(
            max_total_chars=self.live.current_state().budget.max_total_chars
        )

    def source_limit(self) -> int:
        """Bound ordinary evidence and lead reads using the same live ceiling."""
        return self.quota.source_limit(
            max_total_chars=self.live.current_state().budget.max_total_chars
        )
