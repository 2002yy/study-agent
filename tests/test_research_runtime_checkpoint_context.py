"""Checkpoint state projections use the current result buffers after recovery."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from src.application.research_runtime_checkpoint import (
    ActiveRuntimeCheckpointContext,
    ActiveRuntimeCheckpointRecorder,
    ActiveRuntimeCheckpointSession,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.contracts import ResearchBudget, build_research_state
from src.web.research.runtime import ResearchRuntimeCursor
from src.web.research.timing_ledger import TimingLedger


def _checkpoint(
    repository: Mock,
    results: ActiveResearchResultBuffers | None = None,
) -> ActiveRuntimeCheckpointContext:
    return ActiveRuntimeCheckpointContext(
        repository=repository,
        run_id="research-1",
        operation_id="operation-1",
        context={},
        state=build_research_state(
            mode="active",
            questions=(),
            claims=(),
            evidence=(),
            evidence_links=(),
            source_clusters=(),
            gaps=(),
            conflict_gaps=(),
            budget=ResearchBudget(
                max_candidates=5,
                max_reads=2,
                soft_timeout_seconds=10,
                hard_timeout_seconds=20,
            ),
            known_evidence_ids=(),
        ),
        cursor=ResearchRuntimeCursor(),
        results=results
        if results is not None
        else ActiveResearchResultBuffers([], [], [], []),
    )


def test_prepare_failure_rebinds_partial_projection_without_persisting() -> None:
    repository = Mock(spec=WebLookupRepository)
    snapshot = _checkpoint(repository)
    rebound: list[tuple[Any, dict[str, Any]]] = []

    def fail_after_budget_projection(*args: Any, **kwargs: Any) -> None:
        raise ValueError("serialization failed")

    # The cursor projection happened, but Claim Engine serialization failed.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "src.application.research_runtime_checkpoint.attach_claim_engine_state",
            fail_after_budget_projection,
        )
        with pytest.raises(ValueError, match="serialization failed"):
            snapshot.prepare_and_persist(
                stage=None,
                elapsed=lambda: 7.0,
                bind_prepared=lambda s, c: rebound.append((s, c)),
                diagnostics={},
                elapsed_ms=lambda: 0.0,
            )

    assert len(rebound) == 1
    assert rebound[0][0] is snapshot.state
    assert rebound[0][0].budget.elapsed_seconds == 7.0
    assert rebound[0][1] is snapshot.context
    assert rebound[0][1]  # cursor projection was retained
    repository.checkpoint.assert_not_called()


def test_success_rebinds_before_repository_write() -> None:
    events: list[str] = []
    repository = Mock(spec=WebLookupRepository)
    snapshot = _checkpoint(repository)
    persisted = Mock()

    def persist(*args: Any, **kwargs: Any) -> Mock:
        events.append("persist")
        assert events == ["bind", "persist"]
        assert kwargs["research_context"] is snapshot.context
        return persisted

    def bind(state: Any, context: dict[str, Any]) -> None:
        events.append("bind")
        assert state is snapshot.state
        assert context is snapshot.context

    repository.checkpoint.side_effect = persist
    result = snapshot.prepare_and_persist(
        stage=None,
        elapsed=lambda: 4.0,
        bind_prepared=bind,
        diagnostics={},
        elapsed_ms=lambda: 0.0,
    )
    assert result is persisted
    assert events == ["bind", "persist"]


def test_prepare_derives_evidence_ids_from_live_result_buffers(
    monkeypatch: Any,
) -> None:
    import src.application.research_runtime_checkpoint as checkpoint_module

    results = ActiveResearchResultBuffers([], [], [], [])
    ids_at_prepare: list[tuple[str, ...]] = []
    original_attach = checkpoint_module.attach_claim_engine_state

    def capture_evidence_ids(
        context: Any, state: Any, *, known_evidence_ids: Any
    ) -> Any:
        ids_at_prepare.append(tuple(known_evidence_ids))
        return original_attach(context, state, known_evidence_ids=known_evidence_ids)

    # Keep this check independent of source-record format: each new result
    # must be visible to the next checkpoint's identity projection.
    monkeypatch.setattr(
        results,
        "known_evidence_ids",
        lambda run_id: tuple(
            f"{run_id}:{record['id']}" for record in results.selected_sources
        ),
    )
    monkeypatch.setattr(
        checkpoint_module, "attach_claim_engine_state", capture_evidence_ids
    )
    checkpoint = _checkpoint(Mock(spec=WebLookupRepository), results)

    checkpoint.prepare(stage=None, elapsed=lambda: 1.0)
    results.selected_sources.append({"id": "first"})
    checkpoint.prepare(stage=None, elapsed=lambda: 2.0)

    assert ids_at_prepare == [(), ("research-1:first",)]
    assert checkpoint.state.budget.elapsed_seconds == 2.0


def test_checkpoint_session_reloads_live_values_and_rebinds_repository_context() -> (
    None
):
    repository = Mock(spec=WebLookupRepository)
    initial = _checkpoint(repository)
    live = ActiveRuntimeLiveValues(
        state=initial.state,
        cursor=initial.cursor,
        context={"before": "original"},
    )
    seen_contexts: list[dict[str, Any]] = []

    def persist(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        assert kwargs["research_context"] is live.context
        seen_contexts.append(kwargs["research_context"])
        return SimpleNamespace(
            research_context={
                **kwargs["research_context"],
                "steering_from_repository": len(seen_contexts),
            }
        )

    repository.checkpoint.side_effect = persist
    session = ActiveRuntimeCheckpointSession(
        repository=repository,
        run_id="research-1",
        operation_id="operation-1",
        live=live,
        results=initial.results,
        elapsed=lambda: 7.0,
        elapsed_ms=lambda: 0.0,
    )
    first = session.checkpoint(stage=None, diagnostics={})
    assert first.research_context["steering_from_repository"] == 1
    assert live.context is not first.research_context
    assert live.context["steering_from_repository"] == 1
    assert live.state.budget.elapsed_seconds == 7.0

    # A wave handoff replaces the cursor and durable context; the next
    # checkpoint must consume those newest values, not the first snapshot.
    live.cursor = replace(live.cursor, phase="reading")
    live.state = replace(live.state, budget=replace(live.state.budget, max_reads=3))
    live.context = {"after_wave": True}
    session.checkpoint(stage=None, diagnostics={})

    assert len(seen_contexts) == 2
    assert seen_contexts[1]["after_wave"] is True
    assert "before" not in seen_contexts[1]
    assert seen_contexts[1]["claim_engine_runtime"]["phase"] == "reading"
    assert seen_contexts[1]["claim_engine"]["budget"]["max_reads"] == 3
    assert live.context["steering_from_repository"] == 2
    assert repository.checkpoint.call_count == 2


def test_checkpoint_session_keeps_partial_live_projection_on_prepare_failure(
    monkeypatch: Any,
) -> None:
    repository = Mock(spec=WebLookupRepository)
    initial = _checkpoint(repository)
    live = ActiveRuntimeLiveValues(state=initial.state, cursor=initial.cursor)
    session = ActiveRuntimeCheckpointSession(
        repository=repository,
        run_id="research-1",
        operation_id="operation-1",
        live=live,
        results=initial.results,
        elapsed=lambda: 9.0,
        elapsed_ms=lambda: 0.0,
    )

    def fail_serialization(*_args: Any, **_kwargs: Any) -> None:
        raise ValueError("serialization failed")

    monkeypatch.setattr(
        "src.application.research_runtime_checkpoint.attach_claim_engine_state",
        fail_serialization,
    )
    with pytest.raises(ValueError, match="serialization failed"):
        session.checkpoint(stage=None, diagnostics={})

    assert live.state.budget.elapsed_seconds == 9.0
    assert "claim_engine_runtime" in live.context
    repository.checkpoint.assert_not_called()


@pytest.mark.parametrize("persist_fails", [False, True], ids=["success", "failure"])
def test_checkpoint_recorder_observes_latest_live_state_after_persist_attempt(
    persist_fails: bool,
) -> None:
    """A checkpoint's observation must follow the attempted write even on failure."""

    initial = _checkpoint(Mock(spec=WebLookupRepository))
    old_context = {"old": True}
    latest_context = {"after_checkpoint": True}
    live = ActiveRuntimeLiveValues(state=initial.state, context=old_context)
    session = Mock(spec=ActiveRuntimeCheckpointSession)
    ledger = Mock(spec=TimingLedger)
    ledger.current_phase.return_value = "reading"
    events: list[str] = []
    observed: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    persisted = SimpleNamespace(research_context=latest_context)

    def persist(*, stage: str | None, diagnostics: dict[str, Any]) -> Any:
        events.append("persist")
        assert stage == "reading"
        assert diagnostics == {}
        diagnostics["repo_call_ms"] = 3.5
        live.context = latest_context
        if persist_fails:
            raise RuntimeError("checkpoint write failed")
        return persisted

    def record_timing(
        context: dict[str, Any], diagnostics: dict[str, Any], **kwargs: Any
    ) -> None:
        events.append("timing")
        observed.append((context, diagnostics, kwargs))

    session.checkpoint.side_effect = persist
    ledger.record_checkpoint.side_effect = lambda _ms: events.append("ledger")
    times = iter((10.0, 16.0, 19.0))
    recorder = ActiveRuntimeCheckpointRecorder(
        session=session,
        live=live,
        elapsed_ms=lambda: next(times),
        timing_ledger=ledger,
        caller_name=lambda: "settle_completed_wave",
        record_timing=record_timing,
    )

    if persist_fails:
        with pytest.raises(RuntimeError, match="checkpoint write failed"):
            recorder.checkpoint(stage="reading")
    else:
        assert recorder.checkpoint(stage="reading") is persisted

    assert events == ["persist", "ledger", "timing"]
    ledger.record_checkpoint.assert_called_once_with(6.0)
    assert len(observed) == 1
    context, diagnostics, kwargs = observed[0]
    assert context is latest_context and context is not old_context
    assert diagnostics == {"repo_call_ms": 3.5}
    assert kwargs == {
        "wall_ms": 9.0,
        "stage": "reading",
        "caller": "settle_completed_wave",
        "phase": "reading",
    }

@pytest.mark.parametrize("persist_fails", [False, True], ids=["saved", "write_failed"])
@pytest.mark.parametrize("broken_observer", ["ledger", "timing"])
def test_checkpoint_telemetry_failure_preserves_durable_outcome(
    persist_fails: bool,
    broken_observer: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Observation must not turn a durable commit into failure or mask its error."""
    initial = _checkpoint(Mock(spec=WebLookupRepository))
    live = ActiveRuntimeLiveValues(state=initial.state)
    session = Mock(spec=ActiveRuntimeCheckpointSession)
    persisted = SimpleNamespace(research_context={"saved": True})
    if persist_fails:
        session.checkpoint.side_effect = ValueError("repository checkpoint failed")
    else:
        session.checkpoint.return_value = persisted
    ledger = Mock(spec=TimingLedger)
    ledger.current_phase.return_value = "reading"
    timing = Mock()
    if broken_observer == "ledger":
        ledger.record_checkpoint.side_effect = RuntimeError("ledger sink failed")
    else:
        timing.side_effect = RuntimeError("timing sink failed")
    recorder = ActiveRuntimeCheckpointRecorder(
        session=session,
        live=live,
        elapsed_ms=lambda: 5.0,
        timing_ledger=ledger,
        caller_name=lambda: "read",
        record_timing=timing,
    )

    with caplog.at_level("ERROR", logger="src.application.research_runtime_checkpoint"):
        if persist_fails:
            with pytest.raises(ValueError, match="repository checkpoint failed"):
                recorder.checkpoint(stage="reading")
        else:
            assert recorder.checkpoint(stage="reading") is persisted

    session.checkpoint.assert_called_once_with(stage="reading", diagnostics={})
    ledger.record_checkpoint.assert_called_once_with(0.0)
    if broken_observer == "ledger":
        timing.assert_not_called()
    else:
        timing.assert_called_once()
    assert caplog.text.count("research checkpoint timing observation failed") == 1
    assert f"{broken_observer} sink failed" in caplog.text
