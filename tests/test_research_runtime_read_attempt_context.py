"""Per-backend attempt transitions publish the live cursor before observation."""

from dataclasses import fields
from types import SimpleNamespace

import pytest

from src.application.research_runtime_read_attempt_context import (
    ActiveReadAttemptContext,
)
from src.web.research.chain_executor import ChainStepResult
from src.web.research.health_breaker import NATIVE_HTTP_BACKEND
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY
from src.web.research.wigolo_http_executor import WIGOLO_HTTP_BACKEND
from tests.research_read_attempt_factory import read_attempt_recorder
from tests.research_read_candidate_factory import read_candidate


def test_record_chain_attempts_publishes_each_transition_and_escalation() -> None:
    context: dict = {}
    published: list[ResearchRuntimeCursor] = []
    signals: list[tuple[dict, dict, int]] = []
    timestamps = iter(("native-start", "wigolo-start"))
    remaining_samples: list[str] = []
    elapsed_samples: list[str] = []

    def record_escalation(live_context, signal, *, wave_index):
        signals.append((live_context, signal, wave_index))

    attempt_context = read_attempt_recorder(
        breaker=None,
        run_id="run-1",
        utc_now=lambda: next(timestamps),
        on_cursor_change=published.append,
        research_seconds_left=lambda: remaining_samples.append("sample") or 17.0,
        elapsed=lambda: elapsed_samples.append("sample") or 4.0,
        escalation_recorder=record_escalation,
    )
    assert {field.name for field in fields(attempt_context)} == {
        "breaker",
        "run_id",
        "utc_now",
        "on_cursor_change",
        "research_seconds_left",
        "elapsed",
        "escalation_recorder",
    }
    candidate = read_candidate("candidate-a")
    native = ChainStepResult(
        backend=NATIVE_HTTP_BACKEND,
        retrieval_state="timeout",
        usable_content=False,
        adequacy_reason="transport_timeout",
        cost={"error": "TimeoutError: timed out", "latency_ms": 4.0},
        policy={"skip_reason": "timeout"},
    )
    wigolo = ChainStepResult(
        backend=WIGOLO_HTTP_BACKEND,
        retrieval_state="fetched",
        usable_content=True,
        content="supported evidence",
        adequacy_reason="ok",
        cost={"latency_ms": 7.0, "chars": 19, "max_chars_requested": 6000},
    )

    result = attempt_context.record_chain_attempts(
        ResearchRuntimeCursor(phase="reading", wave_index=3),
        context,
        candidate=candidate,
        chain_steps=(native, wigolo),
        attempt_number=2,
        hard_timeout_seconds=60.0,
    )

    native_call = f"research_read:run-1:candidate-a:attempt:2:{NATIVE_HTTP_BACKEND}"
    wigolo_call = f"research_read:run-1:candidate-a:attempt:2:{WIGOLO_HTTP_BACKEND}"
    assert len(published) == 7
    assert published[0].inflight_external_call.call_id == native_call
    assert published[1].inflight_external_call is None
    assert len(published[2].read_outcomes) == 1
    assert len(published[3].failures) == 1
    assert published[4].inflight_external_call.call_id == wigolo_call
    assert published[5].inflight_external_call is None
    assert len(published[6].read_outcomes) == 2

    assert result is published[-1]
    assert result.inflight_external_call is None
    assert [item.backend for item in result.read_outcomes] == [
        "native_http",
        "wigolo_http",
    ]
    assert [item.status for item in result.read_outcomes] == ["failed", "success"]
    assert result.failures[0].attempt_id == native_call
    assert result.failures[0].exception_type == "TimeoutError: timed out"
    assert result.failures[0].provider_code == "timeout"
    assert signals == [
        (
            context,
            {
                "attempted": True,
                "tier": "http",
                "state": "fetched",
                "reason": "ok",
                "rescued": True,
                "shape_before": "transport_timeout",
                "shape_after": "ok",
                "chars_before": 0,
                "chars_after": len("supported evidence"),
                "latency_ms": 7.0,
                "cache_hit": None,
                "max_chars_requested": 6000,
                "preflight": "",
                "url": candidate.url,
                "attempt_seq": 0,
                "research_seconds_left_at_start": 17.0,
                "hard_seconds_left_at_start": 56.0,
                "envelope_remaining_at_start_ms": None,
                "effective_timeout_seconds": None,
            },
            3,
        )
    ]
    assert remaining_samples == ["sample"]
    assert elapsed_samples == ["sample"]
    assert len(context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"]) == 2


def test_cursor_is_published_before_read_observation_can_fail(monkeypatch) -> None:
    published: list[ResearchRuntimeCursor] = []
    candidate = read_candidate("candidate-a")
    attempt_context = read_attempt_recorder(
        run_id="run-1", on_cursor_change=published.append
    )

    def fail_observation(self, context, *, candidate, step, wave_index):
        assert published[-1].read_outcomes[-1].backend == step.backend
        raise RuntimeError("diagnostic sink failed")

    monkeypatch.setattr(ActiveReadAttemptContext, "observe_step", fail_observation)

    with pytest.raises(RuntimeError, match="diagnostic sink failed"):
        attempt_context.record_chain_attempts(
            ResearchRuntimeCursor(phase="reading"),
            {},
            candidate=candidate,
            chain_steps=(
                ChainStepResult(
                    backend=NATIVE_HTTP_BACKEND,
                    retrieval_state="fetched",
                    usable_content=True,
                    content="already-read",
                ),
            ),
            attempt_number=1,
            hard_timeout_seconds=60.0,
        )

    assert len(published) == 3
    assert published[-1].inflight_external_call is None
    assert len(published[-1].read_outcomes) == 1
    assert published[-1].failures == ()


def test_run_bound_recorder_uses_new_cursor_and_context_after_rebind() -> None:
    """Stable callbacks must not become a hidden snapshot of attempt state."""

    first_context: dict = {}
    live = SimpleNamespace(
        cursor=ResearchRuntimeCursor(phase="reading", wave_index=1),
        context=first_context,
    )
    published: list[ResearchRuntimeCursor] = []

    def publish(cursor: ResearchRuntimeCursor) -> None:
        live.cursor = cursor
        published.append(cursor)

    recorder = read_attempt_recorder(
        run_id="stable-run",
        on_cursor_change=publish,
    )
    step = ChainStepResult(
        backend=NATIVE_HTTP_BACKEND,
        retrieval_state="fetched",
        usable_content=True,
        content="body",
    )
    candidate = read_candidate("candidate-a")

    recorder.record_chain_attempts(
        live.cursor,
        live.context,
        candidate=candidate,
        chain_steps=(step,),
        attempt_number=1,
        hard_timeout_seconds=30.0,
    )
    first_published_count = len(published)
    assert first_published_count == 3
    assert first_context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"][0][
        "wave_index"
    ] == 1

    # Simulate a completed checkpoint replacing both values between reads.
    live.cursor = ResearchRuntimeCursor(phase="reading", wave_index=4)
    live.context = {}
    recorder.record_chain_attempts(
        live.cursor,
        live.context,
        candidate=candidate,
        chain_steps=(step,),
        attempt_number=2,
        hard_timeout_seconds=20.0,
    )

    assert len(published) == first_published_count + 3
    assert published[-3].inflight_external_call.call_id == (
        f"research_read:stable-run:candidate-a:attempt:2:{NATIVE_HTTP_BACKEND}"
    )
    assert published[-1] is live.cursor
    assert published[-1].read_outcomes[0].status == "success"
    assert live.context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"][0][
        "wave_index"
    ] == 4
    assert len(first_context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"]) == 1
