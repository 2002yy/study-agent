"""Lead reads preserve crash recovery, cancellation and shared read charges."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.application.research_runtime_discovery_diagnostics import (
    ActiveDiscoveryDiagnosticsContext,
)
from src.application.research_runtime_lead_read_context import (
    ActiveLeadReadAttemptContext,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_budget_context import ReadWaveBudgetContext
from src.application.research_runtime_read_quota_context import ReadWaveQuotaContext
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.contracts import ResearchBudget, build_research_state
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimeExternalAttemptStart,
    _ExternalAttemptBudgetExhausted,
    begin_external_attempt,
    recover_interrupted_external_attempt,
)
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _lead() -> CandidatePoolItem:
    return CandidatePoolItem(
        id="lead-a", canonical_url="https://example.org/lead",
        url="https://example.org/lead", title="Lead", snippet="", source="",
        published_at="", query_ids=(), intents=(), providers=(), first_seen_rank=0,
    )


def _live() -> ActiveRuntimeLiveValues:
    return ActiveRuntimeLiveValues(
        state=build_research_state(
            mode="active", questions=(), claims=(), evidence=(), evidence_links=(),
            source_clusters=(), gaps=(), conflict_gaps=(),
            budget=ResearchBudget(
                max_candidates=5, max_reads=3, reads_used=1,
                soft_timeout_seconds=10, hard_timeout_seconds=20,
            ),
            known_evidence_ids=(),
        ),
        cursor=ResearchRuntimeCursor(phase="reading"),
        context={"run_attempt": 1},
    )


def _context(
    live: ActiveRuntimeLiveValues,
    *,
    gateway_read: Any,
) -> ActiveLeadReadAttemptContext:
    return ActiveLeadReadAttemptContext(
        live=live, run_id="run-a", utc_now=lambda: "2026-11-21T00:00:00Z",
        gateway_read=gateway_read,
        diagnostics=ActiveDiscoveryDiagnosticsContext(live),
    )


def _drive_lead_read(
    attempt: ActiveLeadReadAttemptContext,
    *,
    quota: ReadWaveQuotaContext,
    budget: ReadWaveBudgetContext,
    checkpoint: Any,
    ensure_active: Any = lambda: None,
    source_limit: int = 4,
) -> str | None:
    """Mirror executor checkpoints to assert each intermediate durable value."""
    candidate = _lead()
    marker = attempt.start(candidate)
    checkpoint()
    try:
        raw_read, read_exception = attempt.fetch(candidate, source_limit=source_limit)
    finally:
        attempt.finish(marker)
        checkpoint()
    ensure_active()
    result = attempt.complete(
        candidate=candidate, marker=marker, raw_read=raw_read,
        read_exception=read_exception, source_limit=source_limit,
        quota=quota, budget=budget,
    )
    checkpoint()
    return result


def test_success_persists_started_and_finished_before_charging_rebound_budget() -> None:
    live = _live()
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=10)
    budget = ReadWaveBudgetContext(live, quota, lambda: 4.0)
    snapshots: list[tuple[str | None, tuple[str, ...], int]] = []
    events: list[str] = []

    def checkpoint() -> None:
        events.append("checkpoint")
        inflight = live.cursor.inflight_external_call
        snapshots.append(
            (inflight.call_id if inflight else None, live.cursor.lead_read_ids,
             live.state.budget.reads_used)
        )
        if len(snapshots) == 1:
            # Real persistence/steering may replace both values after start.
            live.context = {**live.context, "run_attempt": 2, "rebound": True}
            live.cursor = replace(live.cursor, wave_index=2)
            live.state = replace(
                live.state, budget=replace(live.state.budget, max_candidates=2)
            )

    def gateway_read(url: str, *, max_chars: int) -> dict[str, Any]:
        events.append("gateway")
        assert len(snapshots) == 1  # start persisted before external work
        assert url == "https://example.org/lead"
        assert max_chars == 4
        assert live.cursor.inflight_external_call is not None
        return {"ok": True, "readme": "longer content"}

    def ensure_active() -> None:
        events.append("ensure_active")
        assert len(snapshots) == 2  # finish persisted before cancellation check
        assert live.cursor.inflight_external_call is None

    content = _drive_lead_read(
        _context(live, gateway_read=gateway_read), checkpoint=checkpoint,
        ensure_active=ensure_active, quota=quota, budget=budget,
    )

    assert content == "long"
    assert events == [
        "checkpoint", "gateway", "checkpoint", "ensure_active", "checkpoint"
    ]
    assert snapshots == [
        ("research_lead_read:run-a:lead-a:attempt:1", (), 1),
        (None, (), 1),
        (None, ("lead-a",), 2),
    ]
    assert (quota.successful_reads, quota.used_chars) == (2, 14)
    assert live.state.budget.elapsed_seconds == 4.0
    assert live.state.budget.max_candidates == 2
    assert live.cursor.wave_index == 2
    assert live.context["rebound"] is True
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovery"] == {
        "lead_read_started": 1
    }


def test_gateway_failure_durably_finishes_then_records_failure_without_charge() -> None:
    live = _live()
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=10)
    budget = ReadWaveBudgetContext(live, quota, lambda: 4.0)
    snapshots: list[tuple[str | None, int, int]] = []

    def checkpoint() -> None:
        inflight = live.cursor.inflight_external_call
        snapshots.append(
            (inflight.call_id if inflight else None,
             len(live.cursor.lead_read_ids), len(live.cursor.failures))
        )

    def gateway_read(url: str, *, max_chars: int) -> dict[str, Any]:
        assert snapshots[0][0] is not None
        raise OSError("reader offline")

    result = _drive_lead_read(
        _context(live, gateway_read=gateway_read), checkpoint=checkpoint,
        quota=quota, budget=budget, source_limit=8,
    )

    assert result is None
    assert snapshots == [
        ("research_lead_read:run-a:lead-a:attempt:1", 0, 0),
        (None, 0, 0),
        (None, 1, 1),
    ]
    assert live.cursor.failures[0].code == "read_failed"
    assert live.cursor.failures[0].exception_type == "OSError"
    assert live.cursor.failures[0].attempt_id == snapshots[0][0]
    assert (quota.successful_reads, quota.used_chars) == (1, 10)
    assert live.state.budget.reads_used == 1
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovery"] == {
        "lead_read_started": 1, "lead_read_failed": 1
    }


def test_cancel_after_gateway_finishes_without_lead_charge_or_third_checkpoint() -> None:
    live = _live()
    quota = ReadWaveQuotaContext(successful_reads=1, used_chars=10)
    budget = ReadWaveBudgetContext(live, quota, lambda: 4.0)
    snapshots: list[str | None] = []

    def checkpoint() -> None:
        inflight = live.cursor.inflight_external_call
        snapshots.append(inflight.call_id if inflight else None)

    def cancelled() -> None:
        raise RuntimeError("cancelled")

    attempt = _context(
        live, gateway_read=lambda url, *, max_chars: {"ok": True, "content": "ok"},
    )
    with pytest.raises(RuntimeError, match="cancelled"):
        _drive_lead_read(
            attempt, checkpoint=checkpoint, ensure_active=cancelled,
            source_limit=8, quota=quota, budget=budget,
        )

    assert snapshots == ["research_lead_read:run-a:lead-a:attempt:1", None]
    assert live.cursor.inflight_external_call is None
    assert live.cursor.lead_read_ids == ()
    assert live.cursor.failures == ()
    assert (quota.successful_reads, quota.used_chars) == (1, 10)


def test_two_interrupted_attempts_reject_third_before_read_or_charge() -> None:
    live = _live()
    attempt = _context(
        live, gateway_read=lambda *_args, **_kwargs: pytest.fail("gateway called"),
    )

    first = attempt.start(_lead())
    assert first.attempt == 1
    live.cursor = recover_interrupted_external_attempt(live.cursor)
    second = attempt.start(_lead())
    assert second.attempt == 2
    live.cursor = recover_interrupted_external_attempt(live.cursor)

    with pytest.raises(_ExternalAttemptBudgetExhausted):
        attempt.start(_lead())

    assert live.cursor.inflight_external_call is None
    assert len(live.cursor.failures) == 2
    assert live.cursor.lead_read_ids == ()
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["lead_discovery"] == {
        "lead_read_started": 2
    }


def test_lead_retry_ignores_evidence_reads_and_similarly_named_leads() -> None:
    live = _live()
    for call_id, item_id in (
        ("research_read:run-a:lead-a:attempt:1:native", "lead-a"),
        ("research_lead_read:run-a:lead-ab:attempt:1", "lead:lead-ab"),
    ):
        live.cursor = recover_interrupted_external_attempt(
            begin_external_attempt(
                live.cursor,
                RuntimeExternalAttemptStart(
                    call_id=call_id, purpose="read", item_id=item_id,
                    attempt=1, started_at="2026-11-21T00:00:00Z",
                ),
            )
        )

    attempt = _context(live, gateway_read=lambda *_args, **_kwargs: {})
    assert attempt.start(_lead()).attempt == 1
    assert len(live.cursor.failures) == 2  # unrelated interruptions remain intact
