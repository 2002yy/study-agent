"""Terminal evidence publication for an active research execution.

The executor owns *when* a run is terminal: steering, the stop gate, and the
final checkpoint must all happen before this context is called.  This context
owns the completed payload only; it never advances a wave or charges a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.application.active_research_evidence_projection import (
    _evidence_brief,
    _format_evidence_brief,
)
from src.application.research_runtime_checkpoint import (
    ActiveResearchResultBuffers,
    _dedupe,
    _eligible_items,
)
from src.application.research_stop_gate import ResearchStopDecision
from src.domain.runtime_entities import WebLookupRun
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchState


@dataclass(frozen=True, slots=True)
class ActiveResearchPublisher:
    """Share one result buffer without capturing a stale research context.

    Values are projected in the historical call-argument order: eligible items,
    formatted evidence, then deduplicated warnings.  In particular, partial
    exception evidence is calculated *after* eligible-item projection.
    """

    repository: WebLookupRepository
    run_id: str
    operation_id: str
    buffers: ActiveResearchResultBuffers

    def complete(
        self,
        *,
        context: dict[str, Any],
        stop: ResearchStopDecision,
        brief: Mapping[str, Any] | None = None,
        state_for_exception: ResearchState | None = None,
        extra_warning: str = "",
        answer_confidence: str | None = None,
        final_status: str | None = None,
    ) -> WebLookupRun:
        """Persist exactly one evidence-bearing terminal completion."""

        return self.repository.complete(
            self.run_id,
            operation_id=self.operation_id,
            items=_eligible_items(self.buffers.selected_sources),
            source_block=self._source_block(brief, state_for_exception),
            warnings=_dedupe(
                [*self.buffers.warnings, extra_warning]
                if extra_warning
                else self.buffers.warnings
            ),
            research_context=context,
            query_attempts=self.buffers.query_attempts,
            selected_sources=self.buffers.selected_sources,
            rejected_sources=self.buffers.rejected_sources,
            provider_status=stop.provider_status,
            stop_reason=stop.reason,
            answer_confidence=(
                stop.answer_confidence
                if answer_confidence is None
                else answer_confidence
            ),
            final_status=stop.final_status if final_status is None else final_status,
        )

    def _source_block(
        self,
        brief: Mapping[str, Any] | None,
        state_for_exception: ResearchState | None,
    ) -> str:
        if brief is None:
            if state_for_exception is None:
                raise ValueError("terminal evidence brief is unavailable")
            brief = _evidence_brief(
                state_for_exception, None, self.buffers.selected_sources
            )
        return _format_evidence_brief(brief)
