"""M4-B: the phase-aware B-Search shadow (lookup / deep) stays inert and non-authoritative."""
from __future__ import annotations

import time

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
