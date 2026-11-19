"""Search projections share one live cursor and audit list across recovery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest import TestCase
from unittest.mock import Mock

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.application.research_runtime_search_outcomes import ActiveSearchOutcomeContext
from src.web.research.candidate_pool import (
    CandidatePoolBatchResult,
    CandidatePoolItem,
    QuerySearchOutcome,
)
from src.web.research.contracts import ResearchState
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.runtime import ResearchRuntimeCursor, RuntimePlannedQuery
from src.web.research.selection_trace import SelectionTraceCollector


def _planned(query_id: str = "q1") -> RuntimePlannedQuery:
    return RuntimePlannedQuery(
        id=query_id, gap_id="gap_1", claim_id="claim_1",
        intent="discovery", query=f"verification {query_id}",
    )


def _candidate(candidate_id: str, url: str, title: str = "Short") -> CandidatePoolItem:
    return CandidatePoolItem(
        id=candidate_id, canonical_url=url, url=url, title=title,
        snippet="excerpt", source="search", published_at="",
        query_ids=(candidate_id,), intents=(GapSearchIntent.DISCOVERY,),
        providers=("primary",), first_seen_rank=1,
    )


def _batch(
    planned: RuntimePlannedQuery,
    *,
    status: str,
    reason: str = "",
    candidates: tuple[CandidatePoolItem, ...] = (),
) -> CandidatePoolBatchResult:
    outcome = QuerySearchOutcome(
        query_id=planned.id,
        intent=GapSearchIntent.DISCOVERY,
        query=planned.query,
        status=status,
        reason=reason,
        result_count=len(candidates),
        providers_attempted=("primary",),
        provider_errors=(("timeout",) if status == "unavailable" else ()),
    )
    return CandidatePoolBatchResult(
        gap_id=planned.gap_id, claim_id=planned.claim_id,
        outcomes=(outcome,), candidates=candidates, status=status,
    )


def _owner(*, cap: int = 3) -> tuple[
    ActiveRuntimeLiveValues, ActiveResearchResultBuffers, ActiveSearchOutcomeContext
]:
    state = cast(ResearchState, SimpleNamespace(budget=SimpleNamespace(max_candidates=cap)))
    live = ActiveRuntimeLiveValues(
        state=state,
        cursor=ResearchRuntimeCursor(phase="searching", wave_index=1),
        context={"run_attempt": 1},
    )
    buffers = ActiveResearchResultBuffers([], [], [], [])
    projector = ActiveSearchOutcomeContext(
        live=live, results=buffers, run_id="run-1", operation_id="op-1",
        trace=SelectionTraceCollector(),
    )
    return live, buffers, projector


class SearchOutcomeContracts(TestCase):
    def test_exhausted_attempt_records_failure_before_outcome_and_audit(self) -> None:
        live, buffers, projector = _owner()
        live.context["claim_engine_steering"] = [
            {"id": "steer-1", "claim_id": "claim_1", "status": "applied"}
        ]
        original_list = buffers.query_attempts
        projector.record_exhausted(_planned())

        self.assertIs(buffers.query_attempts, original_list)
        self.assertEqual(len(live.cursor.failures), 1)
        self.assertEqual(live.cursor.failures[0].code, "search_failed")
        self.assertEqual(live.cursor.failures[0].detail, "external_attempts_exhausted")
        self.assertEqual(live.cursor.query_outcomes[0].status, "unavailable")
        self.assertEqual(live.cursor.query_outcomes[0].error_code, "search_failed")
        self.assertEqual(len(buffers.query_attempts), 1)
        self.assertEqual(buffers.query_attempts[0]["steering_ids"], ["steer-1"])
        self.assertTrue(buffers.query_attempts[0]["influenced_by_steering"])
        self.assertEqual(buffers.query_attempts[0]["providers_attempted"], [])
        self.assertNotIn("provider_audit", buffers.query_attempts[0])

    def test_batch_uses_rebound_budget_context_and_cursor_not_old_snapshot(self) -> None:
        live, buffers, projector = _owner(cap=3)
        first = _planned()
        projector.record_batch(
            first,
            _batch(first, status="ok", candidates=(
                _candidate("a", "https://example.org/a"),
            )),
            call_id="call-1", provider_audit={"provider": "primary"},
        )
        self.assertEqual(len(live.cursor.candidates), 1)
        self.assertEqual(buffers.query_attempts[0]["provider_audit"], {
            "schema_version": "research-provider-audit-v1", "provider": "primary"
        })

        # Recovery/checkpoint may change all live values; the projector stays bound.
        live.context = {"run_attempt": 7}
        live.state = cast(
            ResearchState, SimpleNamespace(budget=SimpleNamespace(max_candidates=1))
        )
        previous_cursor = live.cursor
        second = _planned("q2")
        projector.record_batch(
            second,
            _batch(second, status="ok", candidates=(
                _candidate("b", "https://example.org/b"),
            )),
            call_id="call-2", provider_audit=None,
        )
        self.assertIsNot(live.cursor, previous_cursor)
        self.assertEqual([c.id for c in live.cursor.candidates], ["a"])
        self.assertEqual([o.query_id for o in live.cursor.query_outcomes], ["q1", "q2"])
        self.assertEqual(buffers.query_attempts[-1]["run_attempt"], 7)
        self.assertNotIn("provider_audit", buffers.query_attempts[-1])

    def test_unavailable_batch_keeps_canonical_failure_and_provider_codes(self) -> None:
        live, buffers, projector = _owner()
        planned = _planned()
        projector.record_batch(
            planned,
            _batch(planned, status="unavailable"),
            call_id="call:1", provider_audit={"elapsed_ms": 4},
        )
        self.assertEqual(live.cursor.failures[0].detail, "search_unavailable")
        self.assertEqual(live.cursor.failures[0].attempt_id, "call:1")
        self.assertEqual(live.cursor.failures[0].provider_code, "timeout")
        self.assertEqual(live.cursor.query_outcomes[0].error_code, "search_failed")
        self.assertEqual(buffers.query_attempts[0]["status"], "unavailable")
        self.assertEqual(buffers.query_attempts[0]["provider_errors"], ["timeout"])

    def test_same_url_merges_provenance_without_new_candidate(self) -> None:
        live, _, projector = _owner()
        planned = _planned()
        original_url = "https://example.org/shared"
        projector.record_batch(
            planned, _batch(planned, status="ok", candidates=(
                _candidate("a", original_url),
            )), call_id="call-1", provider_audit=None,
        )
        next_planned = _planned("q2")
        projector.record_batch(
            next_planned, _batch(next_planned, status="ok", candidates=(
                _candidate("b", original_url, "Longer title"),
            )), call_id="call-2", provider_audit=None,
        )
        self.assertEqual(len(live.cursor.candidates), 1)
        self.assertEqual(live.cursor.candidates[0].title, "Longer title")
        self.assertEqual(live.cursor.candidates[0].query_ids, ("a", "b"))

    def test_merge_failure_preserves_failure_without_premature_outcome_or_audit(self) -> None:
        live, buffers, projector = _owner()
        broken_trace = Mock(spec=SelectionTraceCollector)
        broken_trace.note_materialized.side_effect = ValueError("trace failed")
        projector = ActiveSearchOutcomeContext(
            live=live, results=buffers, run_id="run-1", operation_id="op-1",
            trace=cast(SelectionTraceCollector, broken_trace),
        )
        planned = _planned()
        with self.assertRaisesRegex(ValueError, "trace failed"):
            projector.record_batch(
                planned,
                _batch(planned, status="unavailable", candidates=(
                    _candidate("a", "https://example.org/a"),
                )),
                call_id="call-1", provider_audit=None,
            )
        self.assertEqual(len(live.cursor.failures), 1)
        self.assertEqual(live.cursor.query_outcomes, ())
        self.assertEqual(live.cursor.candidates, ())
        self.assertEqual(buffers.query_attempts, [])

    def test_audit_failure_keeps_prior_cursor_projection(self) -> None:
        live, buffers, projector = _owner()
        live.context = {}  # original record path raises after cursor projection
        planned = _planned()
        with self.assertRaises(KeyError):
            projector.record_batch(
                planned, _batch(planned, status="empty"),
                call_id="call-1", provider_audit=None,
            )
        self.assertEqual(live.cursor.query_outcomes[0].status, "empty")
        self.assertEqual(buffers.query_attempts, [])
