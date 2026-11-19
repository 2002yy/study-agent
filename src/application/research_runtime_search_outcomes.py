"""Project a completed search into the live cursor and query audit buffers.

The executor owns external-attempt admission, recovery markers and every
checkpoint. This context only groups the ordered in-memory updates that must
share the current cursor, budget and steering context after the search call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_failure_projection import (
    with_appended_runtime_failure,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.web.research.candidate_pool import CandidatePoolBatchResult, CandidatePoolItem
from src.web.research.runtime import (
    RuntimeCandidate,
    RuntimePlannedQuery,
    RuntimeQueryOutcome,
)
from src.web.research.selection_trace import SelectionTraceCollector
from src.web.research.steering import _steering_ids_for_claim


@dataclass(frozen=True, slots=True)
class ActiveSearchOutcomeContext:
    """One run's search projections; no cached checkpoint or budget snapshot."""

    live: ActiveRuntimeLiveValues
    results: ActiveResearchResultBuffers
    run_id: str
    operation_id: str
    trace: SelectionTraceCollector

    def record_exhausted(self, planned: RuntimePlannedQuery) -> None:
        """Project attempt exhaustion without dispatching another search."""
        self.live.cursor = with_appended_runtime_failure(
            self.live.current_cursor(),
            self.live.current_context(),
            "search_failed",
            "searching",
            logical_call_id=(
                f"research_search:{self.run_id}:{planned.id}:attempts_exhausted"
            ),
            item_id=planned.id,
            detail="external_attempts_exhausted",
        )
        self.live.cursor = replace(
            self.live.current_cursor(),
            query_outcomes=(
                *self.live.current_cursor().query_outcomes,
                RuntimeQueryOutcome(
                    query_id=planned.id,
                    status="unavailable",
                    result_count=0,
                    error_code="search_failed",
                ),
            ),
        )
        self._append_attempt(
            planned,
            status="unavailable",
            reason="external_attempts_exhausted",
            result_count=0,
            providers_attempted=(),
            provider_errors=(),
        )

    def record_batch(
        self,
        planned: RuntimePlannedQuery,
        batch: CandidatePoolBatchResult,
        *,
        call_id: str,
        provider_audit: dict[str, Any] | None,
    ) -> None:
        """Failure → outcome/candidate merge → audit; caller checkpoints next."""
        outcome = batch.outcomes[0]
        if outcome.status == "unavailable":
            self.live.cursor = with_appended_runtime_failure(
                self.live.current_cursor(),
                self.live.current_context(),
                "search_failed",
                "searching",
                logical_call_id=call_id,
                item_id=planned.id,
                detail=outcome.reason or "search_unavailable",
                provider_code=";".join(outcome.provider_errors),
                attempt_id=call_id,
            )
        current_cursor = self.live.current_cursor()
        self.live.cursor = replace(
            current_cursor,
            query_outcomes=(
                *current_cursor.query_outcomes,
                RuntimeQueryOutcome(
                    query_id=planned.id,
                    status=_runtime_query_status(outcome.status),
                    result_count=outcome.result_count,
                    providers=outcome.providers_attempted,
                    error_code=("search_failed" if outcome.status == "unavailable" else ""),
                ),
            ),
            candidates=_merge_runtime_candidates(
                current_cursor.candidates,
                batch.candidates,
                max_candidates=self.live.current_state().budget.max_candidates,
                trace=self.trace,
            ),
        )
        self._append_attempt(
            planned,
            status=outcome.status,
            reason=outcome.reason,
            result_count=outcome.result_count,
            providers_attempted=outcome.providers_attempted,
            provider_errors=outcome.provider_errors,
            provider_audit=provider_audit,
        )

    def _append_attempt(
        self,
        planned: RuntimePlannedQuery,
        *,
        status: str,
        reason: str,
        result_count: int,
        providers_attempted: tuple[str, ...],
        provider_errors: tuple[str, ...],
        provider_audit: dict[str, Any] | None = None,
    ) -> None:
        # Resolve current context after cursor projection. Steering or a previous
        # checkpoint may have replaced the entire dictionary since this wave began.
        context = self.live.current_context()
        self.results.query_attempts.append(
            {
                "query": planned.query,
                "query_id": planned.id,
                "intent": planned.intent,
                "status": status,
                "reason": reason,
                "result_count": result_count,
                "providers_attempted": list(providers_attempted),
                "provider_errors": list(provider_errors),
                "run_attempt": context["run_attempt"],
                "operation_id": self.operation_id,
                "influenced_by_steering": bool(
                    _steering_ids_for_claim(context, planned.claim_id)
                ),
                "steering_ids": list(_steering_ids_for_claim(context, planned.claim_id)),
                **(
                    {
                        "provider_audit": {
                            "schema_version": "research-provider-audit-v1",
                            **provider_audit,
                        }
                    }
                    if provider_audit
                    else {}
                ),
            }
        )


def _runtime_query_status(status: str) -> str:
    return status if status in {"ok", "empty", "unavailable"} else "unavailable"


def _merge_runtime_candidates(
    existing: tuple[RuntimeCandidate, ...],
    incoming: tuple[CandidatePoolItem, ...],
    *,
    max_candidates: int,
    trace: SelectionTraceCollector | None = None,
) -> tuple[RuntimeCandidate, ...]:
    merged = list(existing)
    by_url = {item.url: index for index, item in enumerate(merged)}
    for item in incoming:
        index = by_url.get(item.canonical_url)
        if index is not None:
            if trace is not None:
                trace.note_duplicate(item.canonical_url)
            current = merged[index]
            merged[index] = replace(
                current,
                title=item.title if len(item.title) > len(current.title) else current.title,
                snippet=(
                    item.snippet if len(item.snippet) > len(current.snippet) else current.snippet
                ),
                query_ids=tuple(dict.fromkeys((*current.query_ids, *item.query_ids))),
                intents=tuple(
                    dict.fromkeys(
                        (*current.intents, *(intent.value for intent in item.intents))
                    )
                ),
                providers=tuple(dict.fromkeys((*current.providers, *item.providers))),
            )
            continue
        if len(merged) >= max_candidates:
            if trace is not None:
                trace.note_cap_excluded(item.canonical_url, stage="runtime_merge")
            continue
        by_url[item.canonical_url] = len(merged)
        merged.append(
            RuntimeCandidate(
                id=item.id,
                url=item.canonical_url,
                title=item.title,
                snippet=item.snippet,
                source=item.source,
                published_at=item.published_at,
                query_ids=item.query_ids,
                intents=tuple(intent.value for intent in item.intents),
                providers=item.providers,
                first_seen_rank=item.first_seen_rank,
                parent_lead_candidate_id=item.parent_lead_candidate_id,
                discovery_method=item.discovery_method,
                discovery_depth=item.discovery_depth,
            )
        )
        if trace is not None:
            trace.note_materialized(item.canonical_url)
    return tuple(merged)
