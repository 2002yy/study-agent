"""Thin session adapters backed by SQLite ChatThread/ChatTurn."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.common import (
    SessionArchiveResponse,
    SessionDetailResponse,
    SessionListResponse,
    SessionNewResponse,
)
from src.application.helpers import runtime_settings_payload
from src.application.runtime_repository import get_session_service
from src.application.session_service import SessionService

router = APIRouter(tags=["sessions"])
SessionServiceDependency = Annotated[SessionService, Depends(get_session_service)]


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(
    service: SessionServiceDependency,
    limit: int = 20,
) -> SessionListResponse:
    return SessionListResponse(
        sessions=service.list_sessions(limit=max(1, min(limit, 100)))
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    response_model_exclude_none=True,
)
def get_session_detail(
    session_id: str,
    service: SessionServiceDependency,
) -> SessionDetailResponse:
    detail = service.get_session(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetailResponse(**detail)


@router.post("/sessions/new", response_model=SessionNewResponse)
def create_new_session(service: SessionServiceDependency) -> SessionNewResponse:
    settings = runtime_settings_payload().settings
    thread = service.create_session(dict(settings))
    return SessionNewResponse(session_id=thread.id, settings=settings)


@router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionArchiveResponse,
)
def archive_session(
    session_id: str,
    service: SessionServiceDependency,
) -> SessionArchiveResponse:
    try:
        thread = service.archive_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if thread is None:
        raise HTTPException(status_code=404, detail="Session has no messages to archive")
    return SessionArchiveResponse(
        session_id=thread.id,
        kind="archived",
        path=thread.export_path,
        archived=True,
    )


@router.post("/sessions/{session_id}/flush")
def flush_session(
    session_id: str,
    service: SessionServiceDependency,
) -> dict[str, Any]:
    path = service.flush_session(session_id)
    return {
        "session_id": session_id,
        "flushed": path is not None,
        "path": str(path) if path else "",
    }
