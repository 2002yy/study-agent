"""Compare recorded counters without regrading evidence or inferring quality."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.studyctl_recording import read_recording, summarize_recording


def context_identity(data: dict[str, Any]) -> str:
    question, reference = data.get("question"), data.get("reference_date")
    if not isinstance(question, str) or not question.strip() or len(question) > 16000:
        raise ValueError("question identity unavailable")
    if (
        not isinstance(reference, str)
        or len(reference) != 10
        or date.fromisoformat(reference).isoformat() != reference
    ):
        raise ValueError("reference date unavailable")
    return hashlib.sha256(
        json.dumps([question, reference], ensure_ascii=True).encode()
    ).hexdigest()


def compare_recordings(left: Path, right: Path, run_id: str) -> dict[str, Any]:
    left_raw, left_data = read_recording(left)
    right_raw, right_data = read_recording(right)
    identity = context_identity(left_data)
    if identity != context_identity(right_data):
        raise ValueError("recorded task contexts differ")
    sides = [
        summarize_recording(left_raw, left_data, run_id),
        summarize_recording(right_raw, right_data, run_id),
    ]
    changes = []
    for section, counters in sides[0]["recorded_summary"].items():
        for counter, old in counters.items():
            new = sides[1]["recorded_summary"][section][counter]
            changes.append(
                {
                    "field": section + "." + counter,
                    "left": old,
                    "right": new,
                    "delta": new - old if old is not None and new is not None else None,
                }
            )
    sources = [
        {
            key: side[key]
            for key in (
                "artifact_sha256",
                "run_id",
                "recording_schema_version",
                "recorded_status",
                "recorded_stop_reason",
                "recorded_gate_status",
                "gate_recorded_stop_reason",
                "missing_evidence",
            )
        }
        for side in sides
    ]
    return {
        "status": "PARTIAL",
        "exit_code": 3,
        "errors": [
            {
                "code": "comparison_not_quality_qualification",
                "message": "Recorded count differences do not establish research quality or controlled comparability.",
            }
        ],
        "left": sources[0],
        "right": sources[1],
        "same_artifact": sources[0]["artifact_sha256"] == sources[1]["artifact_sha256"],
        "context_sha256": identity,
        "matched_context": "exact question and reference date",
        "comparison_scope": "recorded counts only; right minus left",
        "changes": changes,
        "missing_provenance": [
            "model_identity",
            "execution_config_identity",
            "complete_event_timeline",
            "citation_support_events",
        ],
        "authority": "diagnostic differences only; no quality score, improvement judgment or publication approval",
    }
