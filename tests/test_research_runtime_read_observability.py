"""Read telemetry projections must stay independent of scheduling decisions."""

import pytest

from src.application.active_research_runtime import (
    _record_escalation_diagnostics as legacy_escalation_diagnostics,
)
from src.application.active_research_runtime import (
    _record_backend_health as legacy_record_backend_health,
)
from src.application.active_research_runtime import (
    _record_read_timing as legacy_record_read_timing,
)
from src.application.research_runtime_read_observability import (
    _record_backend_health,
    _record_escalation_diagnostics,
    _record_read_timing,
)
from src.application.research_runtime_read_attempt_context import (
    ActiveReadAttemptContext,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _candidate() -> CandidatePoolItem:
    return CandidatePoolItem(
        id="candidate-1",
        canonical_url="https://example.test/read",
        url="https://example.test/read",
        title="Title",
        snippet="Snippet",
        source="search",
        published_at="",
        query_ids=(),
        intents=(),
        providers=(),
        first_seen_rank=0,
    )


def test_read_timing_preserves_backend_retry_components_and_legacy_import() -> None:
    assert legacy_record_read_timing is _record_read_timing
    context: dict = {}
    _record_read_timing(
        context,
        candidate=_candidate(),
        wave_index=3,
        status="failed",
        wall_ms=40.0,
        chars=0,
        raw_read={
            "read_retry": {
                "retry_fetch_ms": 20.0,
                "retry_backoff_ms": 5.0,
                "attempts": 2,
                "retries": 1,
                "attempts_detail": [{"index": i} for i in range(6)],
            },
            "escalation": {"latency_ms": 7.0},
            "retrieval_state": "failed",
            "retrieval_policy": {"attempted": True, "backend": "native_http"},
        },
        backend="native_http",
    )

    rows = context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["candidate_id"], row["host"], row["wave_index"]) == (
        "candidate-1",
        "example.test",
        3,
    )
    assert (row["wall_ms"], row["fetch_ms"], row["backoff_ms"]) == (40.0, 20.0, 5.0)
    assert (row["local_ms"], row["escalation_ms"]) == (15.0, 7.0)
    assert (row["attempts"], row["retries"]) == (2, 1)
    assert len(row["attempts_detail"]) == 4
    assert row["retrieval_policy"]["attempted"] is True


def test_read_timing_keeps_80_entries_and_invalid_metrics_untouched() -> None:
    context = {ACTIVE_RESEARCH_METRICS_KEY: {"read_timing": [{"ordinal": i} for i in range(80)]}}
    _record_read_timing(
        context,
        candidate=_candidate(),
        wave_index=1,
        status="success",
        wall_ms=4,
        chars=12,
        raw_read={},
    )
    rows = context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"]
    assert len(rows) == 80
    assert rows[0] == {"ordinal": 1}
    assert rows[-1]["fetch_ms"] == 4.0

    invalid = {ACTIVE_RESEARCH_METRICS_KEY: "legacy-invalid"}
    _record_read_timing(
        invalid,
        candidate=_candidate(),
        wave_index=1,
        status="failed",
        wall_ms=0,
        chars=0,
        raw_read={},
    )
    assert invalid[ACTIVE_RESEARCH_METRICS_KEY] == "legacy-invalid"


def test_backend_health_snapshot_does_not_affect_reader_state() -> None:
    assert legacy_record_backend_health is _record_backend_health
    context: dict = {}
    _record_backend_health(context, None)
    assert context == {}

    class _Breaker:
        def snapshot(self):
            return {"native_http": {"state": "open"}}

    _record_backend_health(context, _Breaker())
    assert context[ACTIVE_RESEARCH_METRICS_KEY]["backend_health"] == {
        "native_http": {"state": "open"}
    }


def test_read_attempt_context_returns_new_cursor_before_observation() -> None:
    recorder = ActiveReadAttemptContext(breaker=None)
    original = ResearchRuntimeCursor(wave_index=2)
    failed_step = ChainStepResult(
        backend="native_http", retrieval_state="timeout", adequacy_reason="timeout"
    )
    updated = recorder.append_outcome(original, _candidate(), failed_step)

    assert original.read_outcomes == ()
    assert updated is not original
    assert updated.read_outcomes[-1].to_dict() == {
        "candidate_id": "candidate-1",
        "status": "failed",
        "evidence_id": "",
        "content_chars": 0,
        "error_code": "read_failed",
        "backend": "native_http",
        "retrieval_state": "timeout",
    }

    class _FailingBreaker:
        def record(self, **kwargs):
            raise RuntimeError("diagnostics unavailable")

    # The caller can hold the updated cursor despite a later telemetry failure.
    recorder.breaker = _FailingBreaker()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="diagnostics unavailable"):
        recorder.observe_step(
            {}, candidate=_candidate(), step=failed_step, wave_index=updated.wave_index
        )
    assert len(updated.read_outcomes) == 1


def test_read_attempt_context_records_same_timing_and_breaker_order() -> None:
    observed = []

    class _Breaker:
        def record(self, **kwargs):
            observed.append(("breaker", kwargs["backend"], kwargs["state"]))

        def snapshot(self):
            observed.append(("snapshot",))
            return {"native_http": "closed"}

    recorder = ActiveReadAttemptContext(breaker=_Breaker())  # type: ignore[arg-type]
    context: dict = {}
    step = ChainStepResult(
        backend="native_http",
        retrieval_state="ok",
        usable_content=True,
        content="verified",
        cost={"latency_ms": 32, "fetch_ms": 20, "backoff_ms": 5, "attempts": 2},
    )
    updated = recorder.append_outcome(ResearchRuntimeCursor(), _candidate(), step)
    recorder.observe_step(context, candidate=_candidate(), step=step, wave_index=4)

    assert observed == [("breaker", "native_http", "ok"), ("snapshot",)]
    assert updated.read_outcomes[-1].content_chars == len("verified")
    metrics = context[ACTIVE_RESEARCH_METRICS_KEY]
    assert metrics["backend_health"] == {"native_http": "closed"}
    timing = metrics["read_timing"][-1]
    assert (timing["wall_ms"], timing["fetch_ms"], timing["backoff_ms"]) == (
        32.0, 20.0, 5.0
    )
    assert timing["wave_index"] == 4


def test_escalation_context_passes_current_context_and_samples_clock_only_if_used() -> None:
    recorded = []
    clock_calls = []

    def capture(context, signal, *, wave_index):
        recorded.append((context, signal, wave_index))

    def remaining():
        clock_calls.append("research")
        return 8.0

    def elapsed():
        clock_calls.append("elapsed")
        return 7.0

    recorder = ActiveReadAttemptContext(breaker=None, escalation_recorder=capture)
    context = {ACTIVE_RESEARCH_METRICS_KEY: {"retrieval_attempt_seq": 13}}
    native = ChainStepResult(
        backend="native_http", retrieval_state="ok", usable_content=True,
        adequacy_reason="adequate",
    )
    recorder.record_escalation_signal(
        context, candidate=_candidate(), native_step=native, wigolo_step=None,
        wave_index=2, research_seconds_left=remaining,
        hard_timeout_seconds=24.0, elapsed=elapsed,
    )
    assert clock_calls == []
    assert recorded[-1][1]["reason"] == "already_adequate"

    wigolo = ChainStepResult(
        backend="wigolo_http", retrieval_state="ok", usable_content=True,
        content="web result", adequacy_reason="adequate",
        cost={"latency_ms": 17, "chars": 10},
    )
    recorder.record_escalation_signal(
        context, candidate=_candidate(), native_step=native, wigolo_step=wigolo,
        wave_index=3, research_seconds_left=remaining,
        hard_timeout_seconds=24.0, elapsed=elapsed,
    )
    assert clock_calls == ["research", "elapsed"]
    assert recorded[-1][0] is context
    assert recorded[-1][2] == 3
    assert recorded[-1][1]["attempt_seq"] == 13
    assert recorded[-1][1]["research_seconds_left_at_start"] == 8.0
    assert recorded[-1][1]["hard_seconds_left_at_start"] == 17.0


def test_moved_escalation_ledger_keeps_invocation_before_attempt_row() -> None:
    assert legacy_escalation_diagnostics is _record_escalation_diagnostics
    context = {ACTIVE_RESEARCH_METRICS_KEY: {}}
    signal = {
        "attempted": True,
        "tier": "http",
        "state": "ok",
        "reason": "short_native",
        "shape_before": "short",
        "shape_after": "adequate",
        "chars_after": 120,
        "latency_ms": 15.5,
    }
    _record_escalation_diagnostics(context, signal, wave_index=2)
    metrics = context[ACTIVE_RESEARCH_METRICS_KEY]
    invocations = metrics["retrieval_invocations"]
    attempts = metrics["retrieval_attempts"]
    assert len(invocations) == 1
    assert len(attempts) == 1
    assert attempts[0]["invocation_id"] == signal["invocation_id"]
    assert invocations[0]["invocation_id"] == signal["invocation_id"]
    assert invocations[0]["state"] == "ok"
    assert invocations[0]["bytes"] == 120

    no_call = {"attempted": False, "state": "ok", "reason": "already_adequate"}
    _record_escalation_diagnostics(context, no_call, wave_index=2)
    assert len(metrics["retrieval_invocations"]) == 1
    assert len(metrics["retrieval_attempts"]) == 2
