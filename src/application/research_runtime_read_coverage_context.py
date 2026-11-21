"""Bind run-level read coverage to the current recovery-safe owner.

Coverage is persisted once, immediately before read planning. This context
holds only stable owner objects, never the replaceable context dictionary or
a snapshot of the current selected-source list.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_coverage import merge_covered_clusters
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers


@dataclass(frozen=True, slots=True)
class ActiveReadCoverageContext:
    """Project selected-source coverage onto the current durable context."""

    live: ActiveRuntimeLiveValues
    results: ActiveResearchResultBuffers

    def merge_current(self) -> dict[str, set[str]]:
        """Resolve both inputs at the call boundary, after any recovery/rebind."""
        return merge_covered_clusters(
            self.live.current_context(), self.results.selected_sources
        )
