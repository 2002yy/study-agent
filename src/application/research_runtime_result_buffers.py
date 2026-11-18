"""Shared research results and evidence projections for checkpoint/publication.

The lists retain their identity across checkpoints. Evidence IDs are always
derived from their current contents, including records added after recovery.
Neither this module nor its projections persist a checkpoint or finish a run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.application.active_research_evidence_projection import _evidence_snapshot


@dataclass
class ActiveResearchResultBuffers:
    """The same mutable lists are consumed by checkpoint and final publication."""

    query_attempts: list[dict[str, Any]]
    selected_sources: list[dict[str, Any]]
    rejected_sources: list[dict[str, Any]]
    warnings: list[str]

    def known_evidence_ids(self, run_id: str) -> tuple[str, ...]:
        """Project live source identities without storing a stale snapshot."""

        snapshot = _evidence_snapshot(
            run_id, self.selected_sources, self.rejected_sources
        )
        return tuple(ref.id for ref in snapshot.refs)


def _eligible_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(record.get("item") or {})
        for record in records
        if isinstance(record.get("extraction"), Mapping)
        and record["extraction"].get("status") == "eligible"
    ]


def _dedupe(values: list[str]) -> list[str]:
    return list(
        dict.fromkeys(str(value)[:500] for value in values if str(value).strip())
    )
