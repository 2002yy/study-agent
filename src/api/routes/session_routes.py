"""Session management endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.models.chat import ChatMessage
from src.api.models.common import (
    SessionArchiveResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionNewResponse,
)
from src.application.helpers import (
    find_session_file,
    messages_from_session_entries,
    parse_archived_session_messages,
    parse_current_session_messages,
    runtime_settings_payload,
    session_file_rows,
    session_snapshot_from_entries,
    session_snapshot_from_raw,
    _api_path,
)

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(limit: int = 20) -> SessionListResponse:
    safe_limit = max(1, min(limit, 100))
    current = session_file_rows(_api_path("CURRENT_SESSION_DIR"), "current", safe_limit)
    archived = session_file_rows(_api_path("SESSION_DIR"), "archived", safe_limit)
    sessions = [*current, *archived]
    sessions.sort(key=lambda row: int(row["mtime_ns"]), reverse=True)
    return SessionListResponse(sessions=sessions[:safe_limit])


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse, response_model_exclude_none=True)
def get_session_detail(session_id: str) -> SessionDetailResponse:
    from src.api import get_session_entries

    entries = get_session_entries(session_id)
    if entries:
        snapshot = session_snapshot_from_entries(entries)
        return SessionDetailResponse(
            session_id=session_id,
            kind="active",
            path="",
            messages=messages_from_session_entries(entries),
            **snapshot,
        )

    kind, path = find_session_file(session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Session not found")

    raw = path.read_text(encoding="utf-8")
    messages = (
        parse_archived_session_messages(raw)
        if kind == "archived"
        else parse_current_session_messages(raw)
    )
    snapshot = session_snapshot_from_raw(raw)
    return SessionDetailResponse(
        session_id=session_id,
        kind=kind,
        path=str(path),
        messages=messages,
        **snapshot,
        raw=raw[:4000],
    )


@router.post("/sessions/new", response_model=SessionNewResponse)
def create_new_session() -> SessionNewResponse:
    from src.api import init_session

    return SessionNewResponse(
        session_id=init_session(),
        settings=runtime_settings_payload().settings,
    )


@router.post("/sessions/{session_id}/archive", response_model=SessionArchiveResponse)
def archive_session(session_id: str) -> SessionArchiveResponse:
    from src.safe_writer import safe_write_text
    from src.api import archive_session_log, get_session_entries

    kind, path = find_session_file(session_id)
    if kind == "archived" and path is not None:
        return SessionArchiveResponse(
            session_id=session_id,
            kind="archived",
            path=str(path),
            archived=True,
        )

    entries = get_session_entries(session_id)
    if not entries and path is None:
        raise HTTPException(status_code=404, detail="Session not found")

    archived_path = archive_session_log(session_id)
    if not archived_path and kind == "current" and path is not None:
        session_dir = _api_path("SESSION_DIR")
        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archived_file = session_dir / f"{timestamp}_session_{session_id}_archived_flash.md"
        safe_write_text(archived_file, path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        archived_path = str(archived_file)
    if not archived_path:
        raise HTTPException(status_code=404, detail="Session has no messages to archive")

    kind, path = find_session_file(session_id)
    return SessionArchiveResponse(
        session_id=session_id,
        kind="archived" if path is not None else kind,
        path=str(path or archived_path),
        archived=True,
    )


@router.post("/sessions/{session_id}/flush")
def flush_session(session_id: str) -> dict[str, Any]:
    from src.api import flush_current_session, get_or_create_session

    get_or_create_session(session_id)
    flushed = flush_current_session(session_id, force=True)
    return {"session_id": session_id, "flushed": flushed}
