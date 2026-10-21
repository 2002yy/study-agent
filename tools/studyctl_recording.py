"""Read the existing B5 smoke recording without importing its live producer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.web.research.failure_contracts import is_research_stop_reason

RECORDING_SCHEMA = "research-quality-b5-active-smoke-v2"
MAX_RECORDING_BYTES = 2 * 1024 * 1024


def unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate recording key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError("non-finite recording value")


def text(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 256
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError("invalid recorded metadata")
    return value


def count(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("invalid recorded count")
    return value


def read_recording(path: Path) -> tuple[bytes, dict[str, Any]]:
    if not path.is_file():
        raise ValueError("recording unavailable")
    with path.open("rb") as file:
        raw = file.read(MAX_RECORDING_BYTES + 1)
    if len(raw) > MAX_RECORDING_BYTES:
        raise ValueError("recording too large")
    data = json.loads(
        raw.decode("utf-8-sig"),
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
    )
    if not isinstance(data, dict) or data.get("schema_version") != RECORDING_SCHEMA:
        raise ValueError("unsupported recording schema")
    return raw, data


def inspect_recording(path: Path, run_id: str) -> dict[str, Any]:
    raw, data = read_recording(path)
    return summarize_recording(raw, data, run_id)


def summarize_recording(
    raw: bytes, data: dict[str, Any], run_id: str
) -> dict[str, Any]:
    run, identity = data.get("run"), data.get("ui_progress")
    if (
        not isinstance(run, dict)
        or not isinstance(identity, dict)
        or identity.get("run_id") != run_id
    ):
        raise ValueError("recording identity unavailable")
    if "id" in run and run["id"] != run_id:
        raise ValueError("conflicting recording identity")
    # The original producer derives progress from the same completed run. Use
    # that field only for correlation, never as evidence or a gate decision.
    summary: dict[str, dict[str, Any]] = {}
    fields = {
        "search": ("query_attempt_count",),
        "candidates": ("count",),
        "reads": ("selected_source_count",),
        "metrics": ("read_count", "cluster_count", "open_critical_gap_count"),
        "gate": ("eligible_evidence_count",),
        "model_calls": ("count",),
    }
    missing = [
        "event_timeline_unavailable",
        "citation_support_events_unavailable",
        "source_bodies_unavailable",
    ]
    for section, names in fields.items():
        source = data.get(section)
        if source is None:
            source = {}
        if not isinstance(source, dict):
            raise ValueError("invalid recorded summary")
        summary[section] = {name: count(source.get(name)) for name in names}
        if any(value is None for value in summary[section].values()):
            missing.append(section + "_summary_incomplete")
    reason = text(run.get("stop_reason"))
    recognized = is_research_stop_reason(reason)
    if not recognized:
        missing.append("stop_reason_missing_or_unknown")
    gate = data.get("gate") or {}
    gate_reason = gate.get("stop_reason")
    if gate_reason is not None:
        gate_reason = text(gate_reason)
        if gate_reason != reason:
            missing.append("conflicting_recorded_stop_reasons")
    gate_status = gate.get("status")
    if gate_status is not None:
        gate_status = text(gate_status)
    return {
        "status": "PARTIAL",
        "exit_code": 3,
        "errors": [
            {
                "code": "insufficient_evidence",
                "message": "Recorded summaries are available; full trace and citation support are absent.",
            }
        ],
        "source_kind": "recorded_smoke_diagnostic",
        "recording_schema_version": RECORDING_SCHEMA,
        "artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "run_id": run_id,
        "identity_source": "ui_progress.run_id (correlation only)",
        "recorded_status": text(run.get("status")),
        "recorded_stage": text(run.get("stage")),
        "provider_status": text(run.get("provider_status")),
        "recorded_stop_reason": reason,
        "stop_reason_recognized": recognized,
        "recorded_gate_status": gate_status,
        "gate_recorded_stop_reason": gate_reason,
        "recorded_summary": summary,
        "events": [],
        "missing_evidence": missing,
        "coverage": {
            "search": "recorded_summary"
            if summary["search"]["query_attempt_count"] is not None
            else "insufficient_evidence",
            "read": "recorded_summary"
            if summary["metrics"]["read_count"] is not None
            else "insufficient_evidence",
            "citation_support": "insufficient_evidence",
            "stop": "recorded_summary" if recognized else "insufficient_evidence",
        },
        "authority": "recorded diagnostic summaries only; no evidence gate or publication approval",
    }
