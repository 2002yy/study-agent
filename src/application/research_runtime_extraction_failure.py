"""Record a failed claim extraction against the current research cursor.

The executor selects the canonical failure code and logical call identity;
this context preserves source-record-before-cursor ordering. Checkpoint and
model-attempt admission remain owned by the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_failure_projection import (
    with_appended_runtime_failure,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.failure_contracts import ResearchFailureCode


@dataclass(frozen=True, slots=True)
class ExtractionFailureContext:
    live: ActiveRuntimeLiveValues

    def record(
        self,
        *,
        source_record: dict[str, Any],
        claim_id: str,
        candidate_id: str,
        reason: str,
        failure_code: ResearchFailureCode,
        logical_call_id: str,
    ) -> None:
        """Write the per-claim failure before appending its runtime audit.

        If audit projection fails, the source retains its partial in-memory
        write while this context leaves the live cursor untouched.
        """

        source_record.setdefault("extractions", {})[claim_id] = {
            "status": "extractor_failed",
            "reason": reason,
        }
        self.live.set_cursor(
            with_appended_runtime_failure(
                self.live.current_cursor(),
                self.live.current_context(),
                failure_code,
                "extracting",
                logical_call_id=logical_call_id,
                item_id=candidate_id,
                detail=reason,
            )
        )
