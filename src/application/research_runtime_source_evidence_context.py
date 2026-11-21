"""Couple projected source publication with optional visual enrichment.

The publication buffer owns source records. A successful text projection is
published *before* visual work so any returned units mutate the exact record
seen by checkpoints and final publication. Neither state nor persistence
state or context snapshot is retained: visual enrichment reads the current
execution owner after source publication.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers

VisualReader = Callable[..., list[dict[str, Any]]]


@dataclass(frozen=True)
class ReadSourceEvidenceContext:
    """Own source upsert → visual read → in-place unit attachment order."""

    results: ActiveResearchResultBuffers
    live: ActiveRuntimeLiveValues
    visual_reader: VisualReader

    def record_projection(
        self,
        record: dict[str, Any],
        *,
        ok: bool,
        canonical_url: str,
    ) -> None:
        self.results.upsert_selected_source(record)
        if not ok:
            return

        # A visual failure is isolated in the injected read-site helper; its
        # diagnostic entries are written to the current persistence context.
        visual_units = self.visual_reader(
            context=self.live.current_context(),
            state=self.live.current_state(),
            canonical_url=canonical_url,
        )
        if visual_units:
            record["visual_units"] = visual_units
