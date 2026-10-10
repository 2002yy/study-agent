"""M4-A: the Standard B-Search shadow must be inert, bounded and non-authoritative."""
from __future__ import annotations

import json
import threading
import time
import types

import src.application.shadow_isolation as iso
from src.application.shadow_isolation import BestEffortTelemetry, submit_shadow_bounded
from src.application.standard_continuation import StandardContinuationService
from src.application.standard_shadow_seam import (
    SHADOW_EVIDENCE_COMPLETION,
    grants_evidence_authority,
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


def _wait_for_items(sink: "_Sink", expected: int = 1, timeout: float = 3.0) -> None:
    """BestEffortTelemetry.flush() only drains the queue; the sink write happens in
    the flusher thread. Wait for the sink itself so assertions are not racy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(sink.items) < expected:
        time.sleep(0.01)


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
    _wait_for_items(sink)
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
    # Deterministically wait for the shared admission tokens to come back, so this
    # test cannot starve later tests in the same session.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if iso.shadow_resource_state()["capacity_available"] == iso.SHADOW_CAPACITY:
            break
        time.sleep(0.01)
    assert iso.shadow_resource_state()["capacity_available"] == iso.SHADOW_CAPACITY


def test_continuation_shadow_helper_never_raises(monkeypatch):
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    service = object.__new__(StandardContinuationService)
    service.shadow_telemetry = None
    service.shadow_runner = lambda q, b: (_ for _ in ()).throw(RuntimeError("boom"))

    # Must raise nothing even when the runner explodes.
    service._observe_standard_shadow(query="q", handoff=None)  # noqa: SLF001


def test_finished_trace_cannot_gain_evidence_authority(monkeypatch):
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    telemetry, sink = _telemetry()

    def runner(query: str, budget: float) -> dict:
        return {
            "stop_reason": "finished",
            "evidence_completion": "SUPPORTED",
            "coverage_audit": {"sub_goals": {"a": {"status": "supported"}}},
        }

    observe_shadow_for_standard(query="q", telemetry=telemetry, runner=runner)
    assert telemetry.flush(timeout=2.0) is True
    _wait_for_items(sink)
    payload = sink.items[0]
    assert grants_evidence_authority(payload) is False
    assert grants_evidence_authority(payload["observation"]) is False
    telemetry.close()


def test_only_an_explicit_audit_grant_could_pass():
    assert grants_evidence_authority({}) is False
    assert grants_evidence_authority(
        {"authoritative": True, "evidence_completion": "SUPPORTED"}) is False
    assert grants_evidence_authority(
        {"authoritative": True, "evidence_completion": "UNVERIFIED", "audit_ref": "x"}
    ) is False
    # the only shape that would ever pass — never produced by this seam
    assert grants_evidence_authority(
        {"authoritative": True, "evidence_completion": "SUPPORTED", "audit_ref": "audit-1"}
    ) is True


def test_flag_on_without_a_sink_refuses_to_spend(monkeypatch):
    """Flag ON with no observable sink must NOT burn model/network budget."""
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    calls: list[str] = []

    result = observe_shadow_for_standard(
        query="q", telemetry=None, runner=lambda q, b: calls.append(q) or {}
    )
    assert result.enabled is True
    assert result.submitted is False
    assert calls == []


def test_service_builds_real_telemetry_when_enabled(monkeypatch):
    """A real Standard service must obtain a sink by itself when the flag is on."""
    from src.application.standard_continuation import _shared_shadow_telemetry

    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    service = StandardContinuationService(
        types.SimpleNamespace(database=object()), runs=object(), gateway=object()
    )
    assert service.shadow_telemetry is not None
    assert service.shadow_telemetry is _shared_shadow_telemetry()  # shared, not per-instance

    monkeypatch.delenv("BSEARCH_STANDARD_SHADOW", raising=False)
    off = StandardContinuationService(
        types.SimpleNamespace(database=object()), runs=object(), gateway=object()
    )
    assert off.shadow_telemetry is None


def test_shared_telemetry_reuses_one_thread_and_closes(monkeypatch):
    """Constructing many services must not multiply flusher threads."""
    from src.application import shadow_telemetry_sink as sink

    monkeypatch.setattr(sink, "_SHARED", None)
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")

    def telemetry_threads() -> int:
        return sum(1 for t in threading.enumerate() if t.name == "shadow-telemetry")

    baseline = telemetry_threads()
    services = [
        StandardContinuationService(
            types.SimpleNamespace(database=object()), runs=object(), gateway=object()
        )
        for _ in range(5)
    ]
    assert len({id(s.shadow_telemetry) for s in services}) == 1  # one shared instance
    assert telemetry_threads() - baseline == 1  # one flusher, not five

    sink.close_shadow_telemetry()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and telemetry_threads() > baseline:
        time.sleep(0.01)
    assert telemetry_threads() == baseline


def test_jsonl_sink_appends_and_never_raises(tmp_path):
    from src.application.shadow_telemetry_sink import JsonlShadowSink

    path = tmp_path / "obs.jsonl"
    sink = JsonlShadowSink(path)
    sink.record({"a": 1})
    sink.record({"b": [1, 2]})
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert sink.written == 2

    # an unusable path must degrade to "no record", never raise
    broken = JsonlShadowSink(tmp_path)  # a directory, not a file
    broken.record({"c": 3})
    assert broken.written == 0


def test_standard_contract_is_unchanged_by_the_generic_seam(monkeypatch, tmp_path):
    """M4-A public result type and telemetry schema must not change silently."""
    import dataclasses

    from src.application import shadow_telemetry_sink as sink
    from src.application.standard_shadow_seam import (
        StandardShadowResult,
        observe_shadow_for_standard,
    )

    assert {f.name for f in dataclasses.fields(StandardShadowResult)} == {
        "enabled",
        "submitted",
        "decision_inputs",
    }

    monkeypatch.setattr(sink, "_SHARED", None)
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    telemetry, rec = _telemetry()
    result = observe_shadow_for_standard(
        query="q", telemetry=telemetry, runner=lambda q, b: {"stop_reason": "finished"}
    )
    assert isinstance(result, StandardShadowResult)
    assert not hasattr(result, "phase")  # M4-A result has no phase field

    assert telemetry.flush(timeout=2.0) is True
    _wait_for_items(rec)
    payload = rec.items[0]
    assert payload["seam_version"] == "standard-bsearch-shadow-seam-v1"
    assert "phase" not in payload  # legacy Standard record shape
    telemetry.close()
    sink.close_shadow_telemetry()
