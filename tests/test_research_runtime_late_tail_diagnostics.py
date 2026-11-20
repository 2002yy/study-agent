"""Live context and terminal-record negative controls for late-tail diagnostics."""

from __future__ import annotations

from types import MappingProxyType

from src.application.research_runtime_late_tail_diagnostics import (
    LateTailDiagnosticsContext,
)


def test_store_rebinds_to_latest_context_without_rewriting_old_metrics() -> None:
    stale = {"claim_engine_metrics": {"domain_targeted": []}}
    rebound = {"claim_engine_metrics": {"domain_targeted": []}}
    holder = [stale]
    samples: list[int] = []

    def now_ms() -> float:
        samples.append(1)
        return 2200.04

    diagnostics = LateTailDiagnosticsContext(
        context=stale,
        current_context=lambda: holder[0],
        now_ms=now_ms,
        deadline_seconds=48.0,
    )
    assert diagnostics.metrics() is stale["claim_engine_metrics"]
    diagnostics.begin(claim_id="claim_1", wave_index=2)
    diagnostics.phase("assessing")
    holder[0] = rebound

    record = {
        "claim_id": "claim_1",
        "wave_index": 2,
        "t_started_ms": 1000.0,
        "t_admitted_ms": 1250.0,
        "t_tail_selected_ms": 2000.0,
        "late_candidate_ids": ["candidate_1"],
        "skipped_reason": "",
        "assessed_ids": ["candidate_1"],
    }
    diagnostics.store(record)

    assert samples == [1]
    assert record["t_tail_gate_ms"] == 2200.0
    assert record["headroom_at_admission_seconds"] == 46.75
    assert record["headroom_at_gate_seconds"] == 45.8
    live = rebound["claim_engine_metrics"]
    assert live["late_assessment_tail"][-1] is record
    critical_path = live["b1_critical_path"][-1]
    assert critical_path["critical_path_ms"] == 1200.0
    assert critical_path["claim_id"] == "claim_1"
    invocation = live["late_tail_invocations"][-1]
    assert invocation["outcome"] == "assessed:1"
    assert invocation["late_ids"] == 1
    assert invocation["recovered"] is True
    assert invocation["metrics_identity_changed"] is True
    assert "late_assessment_tail" not in stale["claim_engine_metrics"]


def test_early_return_and_failure_finish_only_one_invocation_each() -> None:
    context = {"claim_engine_metrics": {"domain_targeted": []}}
    diagnostics = LateTailDiagnosticsContext(context=context)
    diagnostics.begin(claim_id="claim_1", wave_index=2)
    diagnostics.phase("decided:0")
    diagnostics.finish(outcome="no_late_ids")
    diagnostics.begin(claim_id="claim_1", wave_index=2)
    diagnostics.finish(outcome="aborted:ValueError")

    invocations = context["claim_engine_metrics"]["late_tail_invocations"]
    assert [item["invocation_id"] for item in invocations] == [
        "claim_1:2:1", "claim_1:2:2"
    ]
    assert [item["outcome"] for item in invocations] == [
        "no_late_ids", "aborted:ValueError"
    ]
    assert all(item["phase"] == "stored" for item in invocations)
    assert "late_assessment_tail" not in context["claim_engine_metrics"]


def test_readonly_metrics_are_copied_only_for_diagnostics() -> None:
    original = MappingProxyType({"domain_targeted": [{"claim_id": "claim_1"}]})
    context = {"claim_engine_metrics": original}
    diagnostics = LateTailDiagnosticsContext(context=context)
    metrics = diagnostics.metrics()
    assert isinstance(metrics, dict)
    assert metrics["domain_targeted"] is original["domain_targeted"]
    diagnostics.begin(claim_id="claim_1", wave_index=3)
    diagnostics.finish(outcome="no_late_ids")
    assert metrics["late_tail_invocations"][0]["outcome"] == "no_late_ids"
    assert "late_tail_invocations" not in original
