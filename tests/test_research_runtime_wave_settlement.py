"""State handoff at the wave settlement/checkpoint boundary."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from src.application.research_runtime_wave_settlement import (
    ActiveWaveSettlementContext,
    ActiveWaveSettlementSnapshot,
)
from src.application.research_runtime_publication import ActiveResearchPublisher
from src.web.research.contracts import ResearchState
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.runtime import ResearchRuntimeCursor


def test_late_direction_uses_checkpoint_rebound_context_before_publication(
    monkeypatch: Any,
) -> None:
    import src.application.research_runtime_wave_settlement as module

    events: list[str] = []
    steering = Mock()
    steering.refresh.side_effect = lambda value: (events.append("refresh"), value)[1]
    steering.mark_late.side_effect = lambda value, *, reason: (
        events.append(f"late:{reason}"),
        ({**value, "late": True}, ("direction-1",)),
    )[1]

    def checkpoint(snapshot: ActiveWaveSettlementSnapshot) -> None:
        events.append("checkpoint")
        snapshot.context = {**snapshot.context, "durable_updated": True}

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
    settlement = ActiveWaveSettlementContext(
        steering=steering,
        ensure_active=lambda: events.append("active"),
        elapsed=lambda: (events.append("clock"), 70.0)[1],
        checkpoint=checkpoint,
        known_evidence_ids=lambda: (),
        actionable_gaps=lambda _: (),
        publisher=cast(ActiveResearchPublisher, publisher),
        max_research_waves=3,
    )
    snapshot = ActiveWaveSettlementSnapshot(
        state=cast(
            ResearchState,
            SimpleNamespace(budget=SimpleNamespace(hard_timeout_seconds=60.0)),
        ),
        cursor=ResearchRuntimeCursor(wave_index=1),
        context={"claim_engine_steering": [{"id": "direction-1", "status": "pending"}]},
    )

    result = settlement.settle_completed_wave(
        snapshot, cast(EvidenceGateResult, object()), {"brief": "current"}
    )

    assert result is snapshot.context
    assert snapshot.cursor.phase == "completed"
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
