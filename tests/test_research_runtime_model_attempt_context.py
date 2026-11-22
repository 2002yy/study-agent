"""Model attempt callbacks preserve durable-before-send and in-memory finish."""

from dataclasses import fields, replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from src.application.research_runtime_model_attempt_context import (
    ActiveModelAttemptContext,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import ResearchState
from src.web.research.model_gateway import (
    ResearchModelAttemptStart,
    ResearchModelCallAudit,
)
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimeFailure,
    _ModelAttemptBudgetExhausted,
)


def _marker() -> ResearchModelAttemptStart:
    return ResearchModelAttemptStart(
        call_id="claim:1:attempt:1",
        logical_call_id="claim:1",
        purpose="research_claim_planning",
        provider_profile="test",
        model_profile="flash",
        model_name="fake-model",
        attempt=1,
        started_at="2026-11-18T00:00:00Z",
        response_schema_version="test-v1",
        input_sha256="0" * 64,
        input_chars=5,
    )


def _audit(marker: ResearchModelAttemptStart) -> ResearchModelCallAudit:
    return ResearchModelCallAudit(
        call_id=marker.call_id,
        logical_call_id=marker.logical_call_id,
        purpose=marker.purpose,
        provider_profile=marker.provider_profile,
        model_profile=marker.model_profile,
        model_name=marker.model_name,
        attempt=marker.attempt,
        started_at=marker.started_at,
        completed_at="2026-11-18T00:00:01Z",
        elapsed_seconds=1.0,
        status="completed",
        response_schema_version=marker.response_schema_version,
        input_sha256=marker.input_sha256,
        input_chars=marker.input_chars,
    )


def _callbacks(
    *,
    budget_fails: bool = False,
    checkpoint_fails: bool = False,
    cancel_after_finish: bool = False,
) -> tuple[ActiveModelAttemptContext, dict[str, Any], list[str]]:
    slot: dict[str, Any] = {
        "cursor": ResearchRuntimeCursor(),
        "state": cast(ResearchState, object()),
    }
    order: list[str] = []

    def current_state() -> ResearchState:
        order.append("get_state")
        return slot["state"]

    def current_cursor() -> ResearchRuntimeCursor:
        order.append("get_cursor")
        return slot["cursor"]

    def set_cursor(value: ResearchRuntimeCursor) -> None:
        order.append("set_cursor")
        slot["cursor"] = value

    def ensure_active() -> None:
        order.append("ensure_active")
        if cancel_after_finish and slot["cursor"].model_calls:
            raise RuntimeError("cancelled after completion")

    def ensure_budget() -> None:
        # The real guard resolves the latest state before sampling the clock.
        state = current_state()
        order.append("ensure_budget")
        slot["budget_state_seen"] = state
        if budget_fails:
            raise RuntimeError("hard budget reached")

    def checkpoint() -> None:
        order.append("checkpoint")
        if checkpoint_fails:
            raise RuntimeError("checkpoint failed")

    return (
        ActiveModelAttemptContext(
            live=SimpleNamespace(
                current_state=current_state,
                current_cursor=current_cursor,
                set_cursor=set_cursor,
            ),
            ensure_active=ensure_active,
            ensure_budget=ensure_budget,
            checkpoint=checkpoint,
        ),
        slot,
        order,
    )


def test_live_binding_reads_recovered_state_and_rebound_cursor() -> None:
    """Attempt callbacks cannot retain a state/cursor from before recovery."""
    original_state = cast(ResearchState, object())
    recovered_state = cast(ResearchState, object())
    live = ActiveRuntimeLiveValues(state=original_state)
    checked: list[ResearchState] = []
    checkpoints: list[ResearchRuntimeCursor] = []
    callbacks = ActiveModelAttemptContext(
        live=live,
        ensure_active=lambda: None,
        ensure_budget=lambda: checked.append(live.current_state()),
        checkpoint=lambda: checkpoints.append(live.cursor),
    )

    assert {item.name for item in fields(callbacks)} == {
        "live", "ensure_active", "ensure_budget", "checkpoint"
    }
    assert callbacks.live is live
    live.state = recovered_state
    live.cursor = replace(live.cursor, wave_index=2)
    marker = _marker()
    callbacks.started(marker)
    assert checked == [recovered_state]
    assert checkpoints == [live.cursor]
    assert live.cursor.wave_index == 2

    # A wave handoff may replace the cursor after the checkpoint.
    post_checkpoint = replace(live.cursor, phase="searching")
    live.cursor = post_checkpoint
    callbacks.finished(_audit(marker))
    assert live.cursor is not post_checkpoint
    assert live.cursor.inflight_model_call is None
    assert len(live.cursor.model_calls) == 1
    assert len(checkpoints) == 1


def test_model_callbacks_checkpoint_start_before_finish_and_never_flush_audit() -> None:
    callbacks, slot, order = _callbacks()
    marker = _marker()
    callbacks.started(marker)

    assert slot["cursor"].inflight_model_call == marker
    assert slot["cursor"].model_calls == ()
    assert order == [
        "ensure_active", "get_state", "ensure_budget", "get_cursor", "set_cursor", "checkpoint"
    ]

    callbacks.finished(_audit(marker))
    assert slot["cursor"].inflight_model_call is None
    assert len(slot["cursor"].model_calls) == 1
    assert order[-3:] == ["get_cursor", "set_cursor", "ensure_active"]
    assert order.count("checkpoint") == 1, "finished must not persist an audit"


def test_model_callbacks_budget_denial_happens_before_cursor_mutation() -> None:
    callbacks, slot, order = _callbacks(budget_fails=True)
    with pytest.raises(RuntimeError, match="hard budget reached"):
        callbacks.started(_marker())

    assert order == ["ensure_active", "get_state", "ensure_budget"]
    assert slot["cursor"] == ResearchRuntimeCursor()


def test_model_callbacks_checkpoint_crash_retains_in_memory_inflight() -> None:
    callbacks, slot, order = _callbacks(checkpoint_fails=True)
    with pytest.raises(RuntimeError, match="checkpoint failed"):
        callbacks.started(_marker())

    assert order == [
        "ensure_active", "get_state", "ensure_budget", "get_cursor", "set_cursor", "checkpoint"
    ]
    assert slot["cursor"].inflight_model_call == _marker()


def test_model_callbacks_cancel_after_finish_keeps_in_memory_audit() -> None:
    callbacks, slot, order = _callbacks(cancel_after_finish=True)
    marker = _marker()
    callbacks.started(marker)
    with pytest.raises(RuntimeError, match="cancelled after completion"):
        callbacks.finished(_audit(marker))

    assert slot["cursor"].inflight_model_call is None
    assert len(slot["cursor"].model_calls) == 1
    assert order.count("checkpoint") == 1


def test_model_callbacks_read_rebound_cursor_when_started() -> None:
    callbacks, slot, order = _callbacks()
    rebound = ResearchRuntimeCursor(wave_index=7)
    slot["cursor"] = rebound
    callbacks.started(_marker())

    assert rebound.inflight_model_call is None
    assert slot["cursor"].wave_index == 7
    assert slot["cursor"].inflight_model_call == _marker()
    assert order[:4] == ["ensure_active", "get_state", "ensure_budget", "get_cursor"]


def test_model_callbacks_budget_check_reads_rebound_state_at_send_boundary() -> None:
    callbacks, slot, order = _callbacks()
    rebound = cast(ResearchState, object())
    slot["state"] = rebound

    callbacks.started(_marker())

    assert slot["budget_state_seen"] is rebound
    assert order.index("ensure_budget") < order.index("set_cursor")
    assert order.index("checkpoint") > order.index("set_cursor")


def test_attempt_number_admission_uses_current_recovered_cursor_without_side_effects() -> None:
    live = ActiveRuntimeLiveValues(state=cast(ResearchState, object()))
    events: list[str] = []
    callbacks = ActiveModelAttemptContext(
        live=live,
        ensure_active=lambda: events.append("ensure_active"),
        ensure_budget=lambda: events.append("ensure_budget"),
        checkpoint=lambda: events.append("checkpoint"),
    )
    assert callbacks.next_attempt_number("claim:1") == 1

    # A crash has changed the live cursor. It consumes attempt one even
    # without an audit, so resumption may only issue attempt two.
    interrupted_one = RuntimeFailure(
        code="interrupted_unknown", phase="planning", item_id="claim:1:attempt:1"
    )
    live.cursor = replace(live.cursor, failures=(interrupted_one,))
    assert callbacks.next_attempt_number("claim:1") == 2

    interrupted_two = replace(interrupted_one, item_id="claim:1:attempt:2")
    live.cursor = replace(live.cursor, failures=(interrupted_one, interrupted_two))
    before = live.cursor
    with pytest.raises(_ModelAttemptBudgetExhausted):
        callbacks.next_attempt_number("claim:1")

    assert live.cursor is before
    assert events == [], "number admission must not send, charge or checkpoint"
