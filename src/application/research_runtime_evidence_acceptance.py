"""Accept a validated extraction into the live source, state and read cursor.

The result buffers own source records; ActiveRuntimeLiveValues owns the current
state and cursor. This context connects those existing owners without taking
over checkpoint persistence or retaining a replaceable ResearchState snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from src.application.active_research_evidence_projection import (
    _add_extracted_evidence,
    _evidence_id_for_record,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.web.research.active_semantics import ExtractedEvidenceLink


@dataclass(frozen=True, slots=True)
class ExtractedEvidenceAcceptanceContext:
    run_id: str
    live: ActiveRuntimeLiveValues
    results: ActiveResearchResultBuffers

    def accept(
        self,
        *,
        record: dict[str, Any],
        candidate_id: str,
        claim_id: str,
        link: ExtractedEvidenceLink,
    ) -> str:
        """Update the same source object, then state and cursor, in that order.

        Checkpoint stays with the executor immediately after this operation.
        An exception midway keeps the original partial in-memory effects.
        """

        summary = {
            "status": "eligible",
            "claim_id": link.claim_id,
            "relation": link.relation,
            "strength": link.strength,
            "locator": link.locator,
            "anchored_spans": list(link.anchored_spans),
            "caveats": list(link.caveats),
            "source_role": link.source_role,
            "source_cluster_id": link.source_cluster_id,
            "published_at": link.published_at,
        }
        record.setdefault("extractions", {})[claim_id] = dict(summary)
        # Existing consumers read the first eligible singular extraction.
        current_summary = record.get("extraction")
        if not (
            isinstance(current_summary, Mapping)
            and current_summary.get("status") == "eligible"
        ):
            record["extraction"] = summary

        evidence_id = _evidence_id_for_record(
            self.run_id,
            record,
            self.results.selected_sources,
            self.results.rejected_sources,
        )
        self.live.state = _add_extracted_evidence(
            self.live.current_state(), evidence_id=evidence_id, link=link
        )
        cursor = self.live.current_cursor()
        self.live.set_cursor(
            replace(
                cursor,
                read_outcomes=tuple(
                    replace(outcome, evidence_id=evidence_id)
                    if outcome.candidate_id == candidate_id
                    else outcome
                    for outcome in cursor.read_outcomes
                ),
            )
        )
        return evidence_id
