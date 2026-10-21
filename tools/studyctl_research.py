"""Read an offline SQLite snapshot without opening the product database writer."""

from __future__ import annotations

import hashlib
import base64
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

from src.domain.runtime_entities import WebLookupRun
from src.web.research.failure_contracts import is_research_stop_reason
from src.web.research.persistent_memory import known_research_evidence_ids
from src.web.research.state import load_claim_engine_state

MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_CONTEXT_BYTES = 2 * 1024 * 1024


class InvalidCursor(ValueError):
    pass


def read_snapshot(path: Path) -> bytes:
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
    return raw


@contextmanager
def snapshot_connection(raw: bytes) -> Iterator[sqlite3.Connection]:
    # Deserialize into memory: SQLite cannot create journals, migrate, or modify
    # the supplied file. Caller must supply a coherent offline snapshot.
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.deserialize(raw)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        deadline = time.monotonic() + 2
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        connection.row_factory = sqlite3.Row
        yield connection


def encode_cursor(digest: str, after: str) -> str:
    return base64.urlsafe_b64encode(
        json.dumps({"snapshot_sha256": digest, "after": after}, sort_keys=True).encode()
    ).decode()


def decode_cursor(cursor: str, digest: str) -> str:
    if not cursor:
        return ""
    try:
        if len(cursor) > 2048:
            raise ValueError("cursor too long")
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(data, dict) or set(data) != {"snapshot_sha256", "after"}:
            raise ValueError("invalid cursor")
        after = data["after"]
        if (
            not isinstance(after, str)
            or not 0 < len(after) <= 256
            or any(ord(c) < 32 for c in after)
        ):
            raise ValueError("invalid cursor")
        if (
            not isinstance(data["snapshot_sha256"], str)
            or len(data["snapshot_sha256"]) != 64
        ):
            raise ValueError("invalid cursor")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidCursor("invalid cursor") from None
    if data["snapshot_sha256"] != digest:
        raise ValueError("snapshot changed")
    return after


def list_snapshot(path: Path, limit: int, cursor: str = "") -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("invalid page limit")
    raw = read_snapshot(path)
    digest = hashlib.sha256(raw).hexdigest()
    after = decode_cursor(cursor, digest)
    with snapshot_connection(raw) as connection:
        rows = connection.execute(
            "SELECT id, status, stage, stop_reason FROM web_lookup_runs "
            "WHERE (? = '' OR id COLLATE BINARY > ?) ORDER BY id COLLATE BINARY LIMIT ?",
            (after, after, limit + 1),
        ).fetchall()
    records = [dict(row) for row in rows]
    for record in records:
        if any(
            not isinstance(value, str)
            or not value
            or len(value) > 256
            or any(ord(c) < 32 for c in value)
            for key, value in record.items()
            if key != "stop_reason"
        ):
            raise ValueError("invalid catalog metadata")
        reason = record["stop_reason"]
        if (
            not isinstance(reason, str)
            or len(reason) > 256
            or any(ord(c) < 32 for c in reason)
        ):
            raise ValueError("invalid stop reason")
    ids = [record["id"] for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate run identity")
    page = records[:limit]
    return {
        "status": "PASS",
        "exit_code": 0,
        "errors": [],
        "snapshot_sha256": digest,
        "runs": page,
        "has_more": len(records) > limit,
        "next_cursor": encode_cursor(digest, page[-1]["id"])
        if len(records) > limit
        else None,
        "authority": "catalog metadata only; not research quality approval",
    }


def event_cursor(digest: str, run_id: str, sequence: int) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(
            {
                "kind": "research-events-v1",
                "snapshot_sha256": digest,
                "run_id": run_id,
                "after_sequence": sequence,
            },
            sort_keys=True,
        ).encode()
    ).decode()


def event_position(cursor: str, digest: str, run_id: str) -> int:
    if not cursor:
        return -1
    try:
        if len(cursor) > 4096:
            raise ValueError("cursor too long")
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if not isinstance(data, dict) or set(data) != {
            "kind",
            "snapshot_sha256",
            "run_id",
            "after_sequence",
        }:
            raise ValueError("invalid cursor")
        if (
            data["kind"] != "research-events-v1"
            or type(data["after_sequence"]) is not int
            or data["after_sequence"] < 0
        ):
            raise ValueError("invalid cursor")
        if not isinstance(data["run_id"], str) or not isinstance(
            data["snapshot_sha256"], str
        ):
            raise ValueError("invalid cursor")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidCursor("invalid event cursor") from None
    if data["snapshot_sha256"] != digest or data["run_id"] != run_id:
        raise ValueError("event cursor source changed")
    return data["after_sequence"]


def inspect_snapshot(
    path: Path, run_id: str, limit: int = 50, cursor: str = ""
) -> dict[str, Any]:
    """Project recorded facts only; PASS describes inspection, never research quality."""
    raw = read_snapshot(path)
    if not 1 <= limit <= 100:
        raise ValueError("invalid event page limit")
    digest = hashlib.sha256(raw).hexdigest()
    after = event_position(cursor, digest, run_id)
    with snapshot_connection(raw) as connection:
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
        "snapshot_sha256": digest,
        "state_load_status": loaded.status,
        "state_load_reason": loaded.reason,
        "events": [],
        "total_event_count": None,
        "events_returned": 0,
        "has_more": False,
        "next_event_cursor": None,
        "coverage_scope": "whole_recorded_trace",
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
        if cursor and not any(event.sequence == after for event in state.trace):
            raise ValueError("event cursor position unavailable")
        remaining = [event for event in state.trace if event.sequence > after]
        page = remaining[:limit]
        data["events"] = [event.to_dict() for event in page]
        data["total_event_count"] = len(state.trace)
        data["events_returned"] = len(page)
        data["has_more"] = len(remaining) > limit
        data["next_event_cursor"] = (
            event_cursor(digest, run_id, page[-1].sequence)
            if data["has_more"]
            else None
        )
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
