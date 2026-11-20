"""Short-lived diagnostics owner for one late-admission assessment tail.

No scheduling, model admission, budget settlement, checkpoint or evidence writes
belong here. A checkpoint/steering refresh can replace the whole runtime context,
so every metric write resolves the current mapping again.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _b1_critical_path_ms(
    record: Mapping[str, Any], *, deadline_seconds: float
) -> dict[str, Any]:
    """Project B1 admission/tail timing without influencing the run."""

    def _num(key: str) -> float | None:
        value = record.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    admitted_ms = _num("t_admitted_ms")
    selected_ms = _num("t_tail_selected_ms")
    gate_ms = _num("t_tail_gate_ms")
    out: dict[str, Any] = {
        "t_started_ms": _num("t_started_ms"),
        "t_admitted_ms": admitted_ms,
        "t_tail_selected_ms": selected_ms,
        "t_tail_gate_ms": gate_ms,
        "deadline_seconds": round(float(deadline_seconds), 3),
    }
    if admitted_ms is not None:
        out["admission_seconds"] = round(admitted_ms / 1000.0, 3)
        out["headroom_at_admission_seconds"] = round(
            float(deadline_seconds) - admitted_ms / 1000.0, 3
        )
    if gate_ms is not None:
        out["gate_seconds"] = round(gate_ms / 1000.0, 3)
        out["headroom_at_gate_seconds"] = round(
            float(deadline_seconds) - gate_ms / 1000.0, 3
        )
    started_ms = out.get("t_started_ms")
    if started_ms is not None and gate_ms is not None:
        out["critical_path_ms"] = round(gate_ms - started_ms, 1)
    return out


def _resolve_live_metrics(context: dict[str, Any]) -> dict[str, Any] | None:
    """Re-resolve the writable metrics mapping after possible context replacement."""

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if isinstance(metrics, dict):
        return metrics
    if isinstance(metrics, Mapping):
        try:
            writable = dict(metrics)
            context[ACTIVE_RESEARCH_METRICS_KEY] = writable
            return writable
        except Exception:
            return None
    if metrics is None:
        try:
            created: dict[str, Any] = {}
            context[ACTIVE_RESEARCH_METRICS_KEY] = created
            return created
        except Exception:
            return None
    return None


def _metrics_identity(metrics: Mapping[str, Any] | None) -> str:
    return f"{type(metrics).__name__}@{id(metrics):x}" if metrics is not None else ""


def _note_late_tail_invocation(
    context: dict[str, Any], *, claim_id: str, wave_index: int
) -> dict[str, Any] | None:
    """Record invocation identity before any branch can return early."""

    metrics = _resolve_live_metrics(context)
    if metrics is None:
        return None
    invocations = metrics.get("late_tail_invocations")
    if not isinstance(invocations, list):
        invocations = []
    sequence = (
        sum(
            1
            for item in invocations
            if isinstance(item, Mapping)
            and str(item.get("claim_id") or "") == str(claim_id or "")
            and int(item.get("wave_index") or 0) == int(wave_index)
        )
        + 1
    )
    entry: dict[str, Any] = {
        "invocation_id": f"{claim_id}:{wave_index}:{sequence}",
        "claim_id": str(claim_id or ""),
        "wave_index": int(wave_index),
        "late_ids": 0,
        "outcome": "running",
        "phase": "entered",
        "metrics_identity": _metrics_identity(metrics),
        "domain_records": len(metrics.get("domain_targeted") or []),
    }
    invocations.append(entry)
    metrics["late_tail_invocations"] = invocations[-40:]
    return entry


def _finalize_late_tail_invocation(
    context: dict[str, Any],
    entry: Mapping[str, Any] | None,
    *,
    outcome: str,
    late_ids: int = 0,
) -> None:
    """Finalize by stable invocation ID, even after a live mapping replacement."""

    if entry is None:
        return
    if isinstance(entry, dict):
        entry["outcome"] = str(outcome)
        entry["phase"] = "stored"
        entry["late_ids"] = int(late_ids)
    live = _resolve_live_metrics(context)
    if live is None:
        return
    invocations = live.get("late_tail_invocations")
    if not isinstance(invocations, list):
        invocations = []
    target = next(
        (
            item
            for item in invocations
            if isinstance(item, dict)
            and item.get("invocation_id") == entry.get("invocation_id")
        ),
        None,
    )
    if target is None:
        target = dict(entry)
        target["recovered"] = True
        invocations.append(target)
    target["outcome"] = str(outcome)
    target["phase"] = "stored"
    target["late_ids"] = int(late_ids)
    target["store_metrics_identity"] = _metrics_identity(live)
    target["metrics_identity_changed"] = (
        target.get("metrics_identity") != target["store_metrics_identity"]
    )
    live["late_tail_invocations"] = invocations[-40:]


def _record_b1_critical_path(
    context: dict[str, Any], record: Mapping[str, Any], *, deadline_seconds: float
) -> None:
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    records = metrics.get("b1_critical_path")
    if not isinstance(records, list):
        records = []
    payload = dict(_b1_critical_path_ms(record, deadline_seconds=deadline_seconds))
    payload["claim_id"] = str(record.get("claim_id") or "")
    payload["wave_index"] = record.get("wave_index")
    records.append(payload)
    metrics["b1_critical_path"] = records[-40:]


@dataclass
class LateTailDiagnosticsContext:
    """One tail's live metrics, invocation identity, budget-clock observations."""

    context: dict[str, Any]
    current_context: Callable[[], dict[str, Any]] | None = None
    now_ms: Callable[[], float] | None = None
    deadline_seconds: float = 0.0
    invocation: dict[str, Any] | None = field(default=None, init=False)

    def live(self) -> dict[str, Any]:
        return (
            self.current_context()
            if self.current_context is not None
            else self.context
        )

    def metrics(self) -> dict[str, Any] | None:
        return _resolve_live_metrics(self.live())

    def begin(self, *, claim_id: str, wave_index: int) -> None:
        self.invocation = _note_late_tail_invocation(
            self.live(), claim_id=claim_id, wave_index=wave_index
        )

    def phase(self, value: str) -> None:
        if self.invocation is not None:
            self.invocation["phase"] = value

    def finish(self, *, outcome: str, late_ids: int = 0) -> None:
        _finalize_late_tail_invocation(
            self.live(), self.invocation, outcome=outcome, late_ids=late_ids
        )

    def store(self, record: dict[str, Any]) -> None:
        if self.now_ms:
            record["t_tail_gate_ms"] = round(float(self.now_ms()), 1)
        if self.deadline_seconds and record.get("t_admitted_ms") is not None:
            record["headroom_at_admission_seconds"] = round(
                float(self.deadline_seconds) - float(record["t_admitted_ms"]) / 1000.0,
                3,
            )
        if self.deadline_seconds and record.get("t_tail_gate_ms") is not None:
            record["headroom_at_gate_seconds"] = round(
                float(self.deadline_seconds) - float(record["t_tail_gate_ms"]) / 1000.0,
                3,
            )
        _record_b1_critical_path(
            self.live(), record, deadline_seconds=float(self.deadline_seconds or 0.0)
        )
        target = self.metrics()
        if target is None:
            return
        records = target.get("late_assessment_tail")
        if not isinstance(records, list):
            records = []
        records.append(record)
        target["late_assessment_tail"] = records[-40:]
        self.finish(
            outcome=(
                record["skipped_reason"] or f"assessed:{len(record['assessed_ids'])}"
            ),
            late_ids=len(record["late_candidate_ids"]),
        )
