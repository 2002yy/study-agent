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

    def upsert_selected_source(self, record: dict[str, Any]) -> None:
        """Update the live publication list without replacing its list identity."""

        upsert_source_record(self.selected_sources, record)

    def admit_extraction_target(
        self, candidate_id: str, claim_id: str
    ) -> dict[str, Any] | None:
        """Return the live read record only for an unfinished claim binding.

        Preserve first-candidate lookup and the legacy singular extraction
        fallback. An eligible read creates its per-claim map before any model
        admission, just as the executor previously did.
        """

        record = next(
            (
                item
                for item in self.selected_sources
                if item.get("candidate_id") == candidate_id
            ),
            None,
        )
        if record is None:
            return None
        read = record.get("read")
        read_status = str(read.get("status") or "") if isinstance(read, Mapping) else ""
        if read_status != "read":
            return None

        extractions = record.setdefault("extractions", {})
        prior = extractions.get(claim_id)
        if isinstance(prior, Mapping) and prior.get("status") in {
            "eligible",
            "extractor_failed",
        }:
            return None
        legacy = record.get("extraction")
        if (
            prior is None
            and isinstance(legacy, Mapping)
            and legacy.get("status") in {"eligible", "extractor_failed"}
            and legacy.get("claim_id") == claim_id
        ):
            return None
        return record

    def known_evidence_ids(self, run_id: str) -> tuple[str, ...]:
        """Project live source identities without storing a stale snapshot."""

        snapshot = _evidence_snapshot(
            run_id, self.selected_sources, self.rejected_sources
        )
        return tuple(ref.id for ref in snapshot.refs)


def upsert_source_record(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    """Preserve the original candidate upsert order and record aliasing."""

    candidate_id = record.get("candidate_id")
    for index, current in enumerate(records):
        if current.get("candidate_id") == candidate_id:
            records[index] = record
            return
    records.append(record)


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
