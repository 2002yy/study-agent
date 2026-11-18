"""The unified Standard/Lookup/Deep shadow stays inert and non-authoritative."""
from __future__ import annotations

import json
import threading
import time
import types

from src.application import shadow_telemetry_sink as sink
from src.application.research_shadow_seam import (
    PHASE_FLAGS,
    grants_evidence_authority,
    observe_shadow,
    shadow_enabled,
)
from src.application.shadow_isolation import BestEffortTelemetry


class _RecordingSink:
    def __init__(self) -> None:
        self.items: list[object] = []

    def record(self, item: object) -> None:
        self.items.append(item)


def _wait_for_items(rec: _RecordingSink, expected: int = 1, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(rec.items) < expected:
        time.sleep(0.01)


def test_phase_flags_are_independent(monkeypatch):
    for flag in PHASE_FLAGS.values():
        monkeypatch.delenv(flag, raising=False)
    assert [shadow_enabled(p) for p in PHASE_FLAGS] == [False, False, False]

    monkeypatch.setenv(PHASE_FLAGS["deep"], "on")
    assert shadow_enabled("dead") is False  # unknown phase is never enabled
    assert shadow_enabled("deep") is True
    assert shadow_enabled("lookup") is False
    assert shadow_enabled("standard") is False


def test_unknown_phase_cannot_submit():
    result = observe_shadow(phase="nope", query="q")
    assert result.enabled is False
    assert result.submitted is False


def test_standard_phase_is_inert_without_flag_or_observable_sink(monkeypatch):
    monkeypatch.delenv(PHASE_FLAGS["standard"], raising=False)
    calls: list[str] = []
    def runner(query, budget):
        calls.append(query)
        return {}

    disabled = observe_shadow(phase="standard", query="q", runner=runner)
    assert disabled.enabled is False and disabled.submitted is False

    monkeypatch.setenv(PHASE_FLAGS["standard"], "on")
    no_sink = observe_shadow(phase="standard", query="q", runner=runner)
    assert no_sink.enabled is True and no_sink.submitted is False
    assert calls == []


def test_standard_phase_preserves_telemetry_schema_without_compat_wrapper(monkeypatch):
    monkeypatch.setenv(PHASE_FLAGS["standard"], "on")
    rec = _RecordingSink()
    telemetry = BestEffortTelemetry(rec)

    result = observe_shadow(
        phase="standard", query="q", handoff={"query": "q"}, telemetry=telemetry,
        runner=lambda query, budget: {
            "stop_reason": "finished", "authoritative": True,
            "evidence_completion": "SUPPORTED",
        },
    )
    assert result.phase == "standard" and result.submitted is True
    assert result.telemetry_only is True
    assert telemetry.flush(timeout=2.0) is True
    _wait_for_items(rec)
    assert len(rec.items) == 1
    payload = rec.items[0]
    assert payload["seam_version"] == "standard-bsearch-shadow-seam-v1"
    assert "phase" not in payload  # Preserve persisted M4-A record shape.
    assert payload["decision_inputs"] == result.decision_inputs.to_dict()
    assert payload["authoritative"] is False
    assert payload["observation"]["evidence_completion"] == "UNVERIFIED"
    assert grants_evidence_authority(payload) is False
    telemetry.close()


def test_standard_service_uses_one_shared_sink_and_isolates_shadow_failure(monkeypatch):
    from src.application import standard_continuation as continuation

    monkeypatch.setattr(sink, "_SHARED", None)
    monkeypatch.setenv(PHASE_FLAGS["standard"], "on")

    def telemetry_threads() -> int:
        return sum(1 for thread in threading.enumerate() if thread.name == "shadow-telemetry")

    baseline = telemetry_threads()
    services = [
        continuation.StandardContinuationService(
            types.SimpleNamespace(database=object()), runs=object(), gateway=object()
        )
        for _ in range(5)
    ]
    assert len({id(service.shadow_telemetry) for service in services}) == 1
    assert telemetry_threads() == baseline + 1

    forwarded: list[dict] = []

    def explode(**kwargs):
        forwarded.append(kwargs)
        raise RuntimeError("shadow unavailable")

    monkeypatch.setattr(continuation, "observe_shadow", explode)
    services[0]._observe_standard_shadow(query="q", handoff=None)  # noqa: SLF001
    assert len(forwarded) == 1 and forwarded[0]["phase"] == "standard"

    sink.close_shadow_telemetry()
    deadline = time.monotonic() + 3.0
    while telemetry_threads() > baseline and time.monotonic() < deadline:
        time.sleep(0.01)
    assert telemetry_threads() == baseline


def test_shadow_evidence_authority_requires_explicit_independent_audit():
    assert grants_evidence_authority({}) is False
    assert grants_evidence_authority({
        "authoritative": True, "evidence_completion": "SUPPORTED",
    }) is False
    assert grants_evidence_authority({
        "authoritative": True, "evidence_completion": "UNVERIFIED", "audit_ref": "a",
    }) is False
    assert grants_evidence_authority({
        "authoritative": True, "evidence_completion": "SUPPORTED", "audit_ref": "audit-1",
    }) is True


def test_shadow_jsonl_sink_is_append_only_and_best_effort(tmp_path):
    from src.application.shadow_telemetry_sink import JsonlShadowSink

    path = tmp_path / "observations.jsonl"
    target = JsonlShadowSink(path)
    target.record({"a": 1})
    target.record({"b": [1, 2]})
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == [
        {"a": 1}, {"b": [1, 2]},
    ]
    assert target.written == 2

    unavailable = JsonlShadowSink(tmp_path)
    unavailable.record({"c": 3})
    assert unavailable.written == 0


def test_lookup_phase_records_sanitized_telemetry(monkeypatch):
    monkeypatch.setenv(PHASE_FLAGS["lookup"], "on")
    telemetry, rec = BestEffortTelemetry(_RecordingSink()), None
    rec = telemetry._sink  # noqa: SLF001 - test double
    result = observe_shadow(
        phase="lookup", query="q", telemetry=telemetry,
        runner=lambda q, b: {"stop_reason": "finished", "authoritative": True,
                             "evidence_completion": "SUPPORTED"},
    )
    assert result.phase == "lookup" and result.submitted is True
    assert telemetry.flush(timeout=2.0) is True
    _wait_for_items(rec)
    payload = rec.items[0]
    assert payload["phase"] == "lookup"
    assert payload["seam_version"] == "research-bsearch-shadow-seam-v1"
    assert payload["authoritative"] is False
    assert payload["observation"]["evidence_completion"] == "UNVERIFIED"
    assert grants_evidence_authority(payload) is False
    telemetry.close()


def test_lookup_hook_is_a_no_op_when_disabled(monkeypatch):
    from src.application import web_lookup_service as wls

    monkeypatch.delenv(PHASE_FLAGS["lookup"], raising=False)
    calls: list[object] = []
    monkeypatch.setattr(wls, "observe_shadow", lambda **kw: calls.append(kw))
    wls._observe_lookup_shadow("q")  # noqa: SLF001
    assert calls == []


def test_lookup_hook_forwards_the_phase_when_enabled(monkeypatch):
    from src.application import web_lookup_service as wls

    monkeypatch.setenv(PHASE_FLAGS["lookup"], "on")
    calls: list[dict] = []

    def fake_observe(**kw):
        calls.append(kw)

        class _R:
            enabled = True
            submitted = True

        return _R()

    monkeypatch.setattr(wls, "observe_shadow", fake_observe)
    wls._observe_lookup_shadow("lookup query")  # noqa: SLF001
    assert len(calls) == 1
    assert calls[0]["phase"] == "lookup"
    assert calls[0]["query"] == "lookup query"


def test_lookup_hook_swallows_failures(monkeypatch):
    from src.application import web_lookup_service as wls

    monkeypatch.setenv(PHASE_FLAGS["lookup"], "on")

    def boom(**kw):
        raise RuntimeError("observer exploded")

    monkeypatch.setattr(wls, "observe_shadow", boom)
    wls._observe_lookup_shadow("q")  # noqa: SLF001 - must not raise


def test_deep_service_flag_and_helper(monkeypatch):
    import types

    from src.application import deep_continuation as dc

    monkeypatch.setenv(PHASE_FLAGS["deep"], "on")
    service = dc.DeepContinuationService(
        types.SimpleNamespace(database=object()), runs=object(), execution=object()
    )
    assert service.shadow_telemetry is not None

    monkeypatch.delenv(PHASE_FLAGS["deep"], raising=False)
    off = dc.DeepContinuationService(
        types.SimpleNamespace(database=object()), runs=object(), execution=object()
    )
    assert off.shadow_telemetry is None

    # the helper must never raise, even with an exploding observer
    monkeypatch.setenv(PHASE_FLAGS["deep"], "on")
    monkeypatch.setattr(dc, "observe_shadow", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    off._observe_deep_shadow(query="q", handoff=None)  # noqa: SLF001


def test_shared_sink_is_used_across_phases(monkeypatch):
    monkeypatch.setattr(sink, "_SHARED", None)
    assert sink.shadow_telemetry() is sink.shadow_telemetry()
    sink.close_shadow_telemetry()
