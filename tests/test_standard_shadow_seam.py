"""M4-A: the Standard B-Search shadow must be inert, bounded and non-authoritative."""
from __future__ import annotations

import threading

import src.application.shadow_isolation as iso
from src.application.shadow_isolation import BestEffortTelemetry, submit_shadow_bounded
from src.application.standard_continuation import StandardContinuationService
from src.application.standard_shadow_seam import (
    SHADOW_EVIDENCE_COMPLETION,
    observe_shadow_for_standard,
    standard_shadow_enabled,
    summarize_trace,
)


class _Sink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def record(self, item: object) -> None:
        self.items.append(item)


def _telemetry() -> tuple[BestEffortTelemetry, _Sink]:
    sink = _Sink()
    return BestEffortTelemetry(sink), sink


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("BSEARCH_STANDARD_SHADOW", raising=False)
    assert standard_shadow_enabled() is False
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "yes")
    assert standard_shadow_enabled() is True


def test_flag_off_never_runs_the_observer(monkeypatch):
    monkeypatch.delenv("BSEARCH_STANDARD_SHADOW", raising=False)
    calls: list[str] = []

    result = observe_shadow_for_standard(
        query="q", handoff={"query": "q"}, runner=lambda q, b: calls.append(q) or {}
    )
    assert result.enabled is False
    assert result.submitted is False
    assert calls == []


def test_flag_on_records_only_non_authoritative_telemetry(monkeypatch):
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    telemetry, sink = _telemetry()

    def runner(query: str, budget: float) -> dict:
        return {"stop_reason": "finished", "evidence_completion": "SUPPORTED",
                "authoritative": True, "bodies": []}

    result = observe_shadow_for_standard(
        query="研究 X", handoff={"query": "研究 X"}, telemetry=telemetry, runner=runner
    )
    assert result.enabled is True and result.submitted is True
    assert result.telemetry_only is True
    assert telemetry.flush(timeout=2.0) is True
    assert len(sink.items) == 1
    payload = sink.items[0]
    assert payload["authoritative"] is False
    # a shadow record can never claim authority, whatever the runner said
    assert payload["observation"]["authoritative"] is False
    assert payload["observation"]["evidence_completion"] == SHADOW_EVIDENCE_COMPLETION
    telemetry.close()


def test_summarize_pins_authority_false():
    record = summarize_trace(
        {"stop_reason": "finished", "bodies": [{"ok": True, "chars": 10, "url": "u"}],
         "coverage_audit": {"sub_goals": {"a": {"status": "supported"}}}},
        budget_seconds=1.0,
    )
    assert record["authoritative"] is False
    assert record["evidence_completion"] == "UNVERIFIED"


def test_runner_failure_is_swallowed(monkeypatch):
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    telemetry, sink = _telemetry()

    def boom(query: str, budget: float) -> dict:
        raise RuntimeError("observer exploded")

    result = observe_shadow_for_standard(
        query="q", telemetry=telemetry, runner=boom
    )
    assert result.enabled is True  # the call did not raise
    telemetry.flush(timeout=2.0)
    assert sink.items == []  # a failed observation records nothing
    telemetry.close()


def test_shadow_submit_is_non_blocking_and_rejects_on_saturation():
    # Drain the shared admission pool with slow-but-finite jobs.
    release = threading.Event()

    def slow() -> object:
        release.wait(timeout=5.0)
        return "ok"

    accepted = [submit_shadow_bounded(slow) for _ in range(iso.SHADOW_CAPACITY)]
    assert all(accepted)
    rejected: list[object] = []
    assert submit_shadow_bounded(slow, on_result=rejected.append) is False
    assert rejected and rejected[0].status != "ok"
    release.set()


def test_continuation_shadow_helper_never_raises(monkeypatch):
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    service = object.__new__(StandardContinuationService)
    service.shadow_telemetry = None
    service.shadow_runner = lambda q, b: (_ for _ in ()).throw(RuntimeError("boom"))

    # Must not raise even when the runner explodes.
    service._observe_standard_shadow(query="q", handoff=None)  # noqa: SLF001
