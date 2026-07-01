"""Memory preview and commit endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.memory import (
    MemoryCommitResponse,
    MemoryPreviewRequest,
    MemoryPreviewResponse,
    MemoryStatusResponse,
    MemoryRunListResponse,
    MemoryRunResponse,
)
from src.application.memory_service import MemoryService
from src.application.runtime_repository import get_memory_service
from src.application.helpers import (
    extract_latest_section,
    memory_file_row,
)

router = APIRouter(tags=["memory"])
MemoryServiceDependency = Annotated[MemoryService, Depends(get_memory_service)]


def _run_response(run) -> MemoryRunResponse:
    return MemoryRunResponse(**asdict(run))


@router.get("/memory", response_model=MemoryStatusResponse)
def get_memory_status(context_mode: str | None = None) -> MemoryStatusResponse:
    from src import api as _api  # imported via api proxy for monkeypatch

    from src.memory import CONTEXT_FILE_GROUPS

    modes = _api.load_runtime_modes()
    resolved_context_mode = context_mode or modes.context_mode
    if resolved_context_mode not in CONTEXT_FILE_GROUPS:
        raise HTTPException(status_code=400, detail=f"Invalid context_mode: {resolved_context_mode}")
    writable = _api.is_memory_write_allowed(modes)
    file_names = list(dict.fromkeys(CONTEXT_FILE_GROUPS["archive"]))
    files = [memory_file_row(name) for name in file_names]
    return MemoryStatusResponse(
        writable=writable,
        memory_mode=modes.memory_mode,
        safe_mode=modes.safe_mode,
        reason=modes.profile.memory_write_reason,
        context_mode=resolved_context_mode,
        groups=CONTEXT_FILE_GROUPS,
        files=files,
        latest_section=extract_latest_section(_api.read_memory_file("current_focus.md")),
        latest_updated_at="",
    )


@router.post("/memory-runs", response_model=MemoryRunResponse)
def create_memory_run(
    request: MemoryPreviewRequest,
    service: MemoryServiceDependency,
) -> MemoryRunResponse:
    try:
        return _run_response(
            service.create([update.model_dump() for update in request.updates])
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/memory-runs", response_model=MemoryRunListResponse)
def list_memory_runs(
    service: MemoryServiceDependency,
    limit: int = 20,
) -> MemoryRunListResponse:
    return MemoryRunListResponse(
        runs=[_run_response(run) for run in service.list(limit=limit)]
    )


@router.get("/memory-runs/{run_id}", response_model=MemoryRunResponse)
def get_memory_run(
    run_id: str,
    service: MemoryServiceDependency,
) -> MemoryRunResponse:
    try:
        return _run_response(service.get(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/memory-runs/{run_id}/commit", response_model=MemoryRunResponse)
def commit_memory_run(
    run_id: str,
    service: MemoryServiceDependency,
) -> MemoryRunResponse:
    try:
        return _run_response(service.commit(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/memory/preview", response_model=MemoryPreviewResponse, deprecated=True)
def preview_memory_updates(
    request: MemoryPreviewRequest,
    service: MemoryServiceDependency,
) -> MemoryPreviewResponse:
    from src.api import load_runtime_modes

    try:
        run = service.create(
            [update.model_dump() for update in request.updates],
            runtime_modes=load_runtime_modes(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MemoryPreviewResponse(**run.preview)


@router.post("/memory/commit", response_model=MemoryCommitResponse)
def commit_memory_updates(
    request: MemoryPreviewRequest,
    service: MemoryServiceDependency,
) -> MemoryCommitResponse:
    from src.api import load_runtime_modes

    modes = load_runtime_modes()
    try:
        created = service.create(
            [update.model_dump() for update in request.updates],
            runtime_modes=modes,
        )
        committed = service.commit(created.id, runtime_modes=modes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if committed.status == "blocked":
        raise HTTPException(
            status_code=403,
            detail={
                "memory_mode": modes.memory_mode,
                "safe_mode": modes.safe_mode,
                "reason": committed.reason,
            },
        )
    results = committed.result.get("results", [])
    errors = committed.result.get("errors", [])
    if committed.status == "failed":
        raise HTTPException(
            status_code=500,
            detail={"message": "所有写入均失败", "errors": errors},
        )
    return MemoryCommitResponse(
        writable=True,
        results=results,
        errors=errors or None,
    )
