"""Live-owner wave settlement preserves recovery and checkpoint ordering."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_publication import ActiveResearchPublisher
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.application.research_runtime_wave_settlement import ActiveWaveSettlementContext
from src.web.research.contracts import ResearchState
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor


class _InterruptedWave(BaseException):
    pass


def _live_wave(
    *,
    hard_seconds: float = 60.0,
    wave_index: int = 1,
    context: dict[str, Any] | None = None,
) -> ActiveRuntimeLiveValues:
    return ActiveRuntimeLiveValues(
        state=cast(
            ResearchState,
            SimpleNamespace(budget=SimpleNamespace(hard_timeout_seconds=hard_seconds)),
        ),
        cursor=ResearchRuntimeCursor(wave_index=wave_index),
        context={} if context is None else context,
    )


def _settlement(
    live: ActiveRuntimeLiveValues,
    *,
    steering: Mock | None = None,
    checkpoint: Any = None,
    elapsed: Any = None,
    results: ActiveResearchResultBuffers | None = None,
    publisher: Mock | None = None,
    ensure_active: Any = None,
) -> ActiveWaveSettlementContext:
    steering = steering or Mock()
    if steering.refresh.side_effect is None:
        steering.refresh.side_effect = lambda value: value
    return ActiveWaveSettlementContext(
        live=live,
        steering=steering,
        ensure_active=ensure_active or (lambda: None),
        elapsed=elapsed or (lambda: 5.0),
        checkpoint=checkpoint or (lambda: None),
        results=(
            results
            if results is not None
            else ActiveResearchResultBuffers([], [], [], [])
        ),
        run_id="research-1",
        actionable_gaps=lambda _: (),
        publisher=cast(ActiveResearchPublisher, publisher or Mock()),
        max_research_waves=3,
    )


def test_pending_direction_keeps_prepared_checkpoint_values_on_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No outer snapshot may overwrite a partially prepared persisted context."""
    import src.application.research_runtime_wave_settlement as module

    monkeypatch.setattr(module, "_pending_active_steering_ids", lambda _: ("pending",))
    live = _live_wave()
    applied_state = cast(ResearchState, object())
    prepared_state = cast(ResearchState, object())
    steering = Mock()
    steering.apply_pending.return_value = (
        applied_state,
        {"direction_applied": True},
        ("pending",),
    )

    def interrupt() -> None:
        assert live.state is applied_state
        assert (live.cursor.wave_index, live.cursor.phase) == (2, "searching")
        live.state = prepared_state
        live.context = {"checkpoint_prepared": True}
        raise _InterruptedWave

    settlement = _settlement(live, steering=steering, checkpoint=interrupt)
    with pytest.raises(_InterruptedWave):
        settlement.settle_completed_wave(cast(EvidenceGateResult, object()), {})

    assert live.state is prepared_state
    assert live.cursor.wave_index == 2
    assert live.cursor.phase == "searching"
    assert live.context == {"checkpoint_prepared": True}
    steering.apply_pending.assert_called_once()


def test_continue_checkpoint_failure_keeps_live_cursor_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.research_runtime_wave_settlement as module

    monkeypatch.setattr(module, "_pending_active_steering_ids", lambda _: ())
    monkeypatch.setattr(module, "completed_wave_stop_signal", lambda **_: object())
    monkeypatch.setattr(
        module.ResearchStopGate,
        "evaluate",
        lambda _: SimpleNamespace(decision="continue"),
    )
    live = _live_wave()
    prepared_context = {"repository_projection": True}
    published = Mock()

    def interrupt() -> None:
        assert (live.cursor.wave_index, live.cursor.phase) == (2, "searching")
        live.context = prepared_context
        raise _InterruptedWave

    settlement = _settlement(live, checkpoint=interrupt, publisher=published)
    with pytest.raises(_InterruptedWave):
        settlement.settle_completed_wave(cast(EvidenceGateResult, object()), {})

    assert live.cursor.wave_index == 2
    assert live.context is prepared_context
    published.complete.assert_not_called()


def test_late_direction_uses_checkpoint_rebound_context_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.research_runtime_wave_settlement as module

    events: list[str] = []
    steering = Mock()
    steering.refresh.side_effect = lambda value: (events.append("refresh"), value)[1]
    steering.mark_late.side_effect = lambda value, *, reason: (
        events.append(f"late:{reason}"),
        ({**value, "late": True}, ("direction-1",)),
    )[1]
    live = _live_wave(
        context={"claim_engine_steering": [{"id": "direction-1", "status": "pending"}]}
    )

    def checkpoint() -> None:
        events.append("checkpoint")
        # Existing diagnostic caller name is part of the observation contract.
        assert sys._getframe(1).f_code.co_name == "settle_completed_wave"
        live.context = {**live.context, "durable_updated": True}

    def stop_signal(**kwargs: Any) -> Any:
        events.append("signal")
        assert kwargs["context"]["durable_updated"] is True
        assert kwargs["context"]["late"] is True
        return object()

    def evaluate(_: Any) -> Any:
        events.append("stop")
        return SimpleNamespace(decision="success")

    monkeypatch.setattr(module, "completed_wave_stop_signal", stop_signal)
    monkeypatch.setattr(module.ResearchStopGate, "evaluate", evaluate)
    publisher = Mock()
    publisher.complete.side_effect = lambda **kwargs: (
        events.append("publish"),
        kwargs["context"],
    )[1]
    settlement = _settlement(
        live,
        steering=steering,
        checkpoint=checkpoint,
        elapsed=lambda: (events.append("clock"), 70.0)[1],
        publisher=publisher,
        ensure_active=lambda: events.append("active"),
    )

    result = settlement.settle_completed_wave(
        cast(EvidenceGateResult, object()), {"brief": "current"}
    )

    assert result is live.context
    assert live.cursor.phase == "completed"
    assert events == [
        "active",
        "refresh",
        "clock",
        "late:hard_budget_exhausted",
        "checkpoint",
        "signal",
        "stop",
        "checkpoint",
        "publish",
    ]


def test_pending_direction_reads_current_evidence_ids_after_context_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.research_runtime_wave_settlement as module

    live = _live_wave()
    results = ActiveResearchResultBuffers([], [], [], [])
    monkeypatch.setattr(
        results,
        "known_evidence_ids",
        lambda run_id: tuple(
            f"{run_id}:{source['id']}" for source in results.selected_sources
        ),
    )
    monkeypatch.setattr(
        module, "_pending_active_steering_ids", lambda _: ("new-direction",)
    )
    steering = Mock()

    def apply_pending(
        *, state: Any, context: Any, known_evidence_ids: Any, **_: Any
    ) -> Any:
        assert known_evidence_ids() == ("research-1:fresh-source",)
        return state, context, ("new-direction",)

    steering.apply_pending.side_effect = apply_pending
    checkpoints: list[tuple[int, str]] = []
    settlement = _settlement(
        live,
        steering=steering,
        results=results,
        checkpoint=lambda: checkpoints.append(
            (live.cursor.wave_index, live.cursor.phase)
        ),
    )
    results.selected_sources.append({"id": "fresh-source"})

    assert settlement.settle_completed_wave(
        cast(EvidenceGateResult, object()), {}
    ) is None
    assert checkpoints == [(2, "searching")]
    assert live.cursor.wave_index == 2


def test_terminal_publication_observes_checkpoint_rebound_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.application.research_runtime_wave_settlement as module

    monkeypatch.setattr(module, "_pending_active_steering_ids", lambda _: ())
    monkeypatch.setattr(module, "completed_wave_stop_signal", lambda **_: object())
    monkeypatch.setattr(
        module.ResearchStopGate,
        "evaluate",
        lambda _: SimpleNamespace(decision="success"),
    )
    live = _live_wave(context={"before": True})
    publisher = Mock()
    events: list[str] = []

    def checkpoint() -> None:
        events.append("checkpoint")
        assert live.cursor.phase == "completed"
        live.context = {"persisted": True}

    def publish(**kwargs: Any) -> Any:
        events.append("publish")
        assert kwargs["context"] is live.context
        return kwargs["context"]

    publisher.complete.side_effect = publish
    settlement = _settlement(live, checkpoint=checkpoint, publisher=publisher)

    result = settlement.settle_completed_wave(
        cast(EvidenceGateResult, object()), {"brief": "current"}
    )
    assert result is live.context
    assert result == {"persisted": True}
    assert events == ["checkpoint", "publish"]
