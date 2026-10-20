"""Read an offline SQLite snapshot without opening the product database writer."""

from __future__ import annotations

import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

from src.domain.runtime_entities import WebLookupRun
from src.web.research.failure_contracts import is_research_stop_reason
from src.web.research.persistent_memory import known_research_evidence_ids
from src.web.research.state import load_claim_engine_state

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_CONTEXT_BYTES = 2 * 1024 * 1024


def inspect_snapshot(path: Path, run_id: str) -> dict[str, Any]:
    """Project recorded facts only; PASS describes inspection, never research quality."""
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError("offline_snapshot_required")
    if any(
        Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ValueError("offline_snapshot_required")
    with path.open("rb") as file:
        raw = file.read(MAX_DATABASE_BYTES + 1)
    if len(raw) > MAX_DATABASE_BYTES or not raw.startswith(b"SQLite format 3\x00"):
        raise ValueError("invalid_database_snapshot")
    # Deserialize into memory: SQLite cannot create journals, migrate, or modify
    # the supplied file. Caller must supply a coherent offline snapshot.
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(raw)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, status, stage, provider_status, stop_reason, "
            "research_context, selected_sources, rejected_sources "
            "FROM web_lookup_runs WHERE id = ? LIMIT 2",
            (run_id,),
        ).fetchall()
    if len(row) != 1:
        raise ValueError("run_not_uniquely_found")
    record = dict(row[0])
    for name, expected in (
        ("research_context", dict),
        ("selected_sources", list),
        ("rejected_sources", list),
    ):
        value = record[name]
        if not isinstance(value, str) or len(value) > MAX_CONTEXT_BYTES:
            raise ValueError("invalid_record")
        record[name] = json.loads(value)
        if not isinstance(record[name], expected):
            raise ValueError("invalid_record")
    for name in ("id", "status", "stage", "provider_status", "stop_reason"):
        if not isinstance(record[name], str) or len(record[name]) > 256:
            raise ValueError("invalid_record")
    run = WebLookupRun(**record)
    loaded = load_claim_engine_state(
        run.research_context, known_evidence_ids=known_research_evidence_ids(run)
    )
    missing: list[str] = []
    data: dict[str, Any] = {
        "run_id": run.id,
        "recorded_status": run.status,
        "recorded_stage": run.stage,
        "provider_status": run.provider_status,
        "recorded_stop_reason": run.stop_reason,
        "stop_reason_recognized": is_research_stop_reason(run.stop_reason),
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "state_load_status": loaded.status,
        "state_load_reason": loaded.reason,
        "events": [],
        "coverage": {},
        "missing_evidence": missing,
        "authority": "recorded diagnostics only; no publication or answer-quality approval",
    }
    state = loaded.state
    if state is None:
        missing.append(loaded.reason)
    elif any(event.run_id != run.id for event in state.trace):
        # Reject the entire timeline rather than silently attributing a foreign
        # event to the requested run or filtering away the provenance failure.
        missing.append("cross_run_trace")
    else:
        data["events"] = [event.to_dict() for event in state.trace]
        groups = {
            "search": {"search_completed"},
            "read": {"read_completed"},
            "citation_support": {"claim_linked", "gate_evaluated"},
            "stop": {"stop_allowed", "stop_blocked"},
        }
        observed = {event.event_type for event in state.trace}
        for label, required in groups.items():
            present = (
                required <= observed
                if label == "citation_support"
                else bool(required & observed)
            )
            data["coverage"][label] = "recorded" if present else "insufficient_evidence"
            if not present:
                missing.append(label + "_events_missing")
    if not data["stop_reason_recognized"]:
        missing.append("stop_reason_missing_or_unknown")
    return {
        "status": "PARTIAL" if missing else "PASS",
        "exit_code": 3 if missing else 0,
        "errors": (
            [
                {
                    "code": "insufficient_evidence",
                    "message": "Recorded evidence is incomplete; no inferred failure reason.",
                }
            ]
            if missing
            else []
        ),
        **data,
    }
