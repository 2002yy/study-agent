"""Tool and workflow endpoints."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.common import (
    ToolInvocationRequest,
    ToolInvocationResponse,
    ToolListResponse,
    ToolRunCreateRequest,
    ToolRunListResponse,
    ToolRunResponse,
    WorkflowListResponse,
    WorkflowRunResponse,
)
from src.application.runtime_repository import get_tool_service
from src.application.tool_service import ToolService

router = APIRouter(tags=["tools"])
ToolServiceDependency = Annotated[ToolService, Depends(get_tool_service)]


def _tool_run_response(run) -> ToolRunResponse:
    return ToolRunResponse(**asdict(run))


@router.get("/tools", response_model=ToolListResponse)
def list_tools() -> ToolListResponse:
    from src.api.app import TOOL_REGISTRY

    return ToolListResponse(tools=[spec.to_dict() for spec in TOOL_REGISTRY.list_specs()])


@router.post("/tools/{tool_name}/preview", response_model=ToolInvocationResponse)
def preview_tool(tool_name: str, request: ToolInvocationRequest) -> ToolInvocationResponse:
    del tool_name, request
    raise HTTPException(status_code=410, detail="Use POST /tool-runs")


@router.post("/tools/{tool_name}/call", response_model=ToolInvocationResponse)
def call_tool(tool_name: str, request: ToolInvocationRequest) -> ToolInvocationResponse:
    del tool_name, request
    raise HTTPException(status_code=410, detail="Use POST /tool-runs/{id}/call")


@router.post("/tool-runs", response_model=ToolRunResponse)
def create_tool_run(
    request: ToolRunCreateRequest, service: ToolServiceDependency
) -> ToolRunResponse:
    return _tool_run_response(service.create(request.tool_name, request.args))


@router.post("/tool-runs/{run_id}/call", response_model=ToolRunResponse)
def call_tool_run(run_id: str, service: ToolServiceDependency) -> ToolRunResponse:
    try:
        return _tool_run_response(service.call(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tool-runs/{run_id}", response_model=ToolRunResponse)
def get_tool_run(run_id: str, service: ToolServiceDependency) -> ToolRunResponse:
    try:
        return _tool_run_response(service.get(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tool-runs", response_model=ToolRunListResponse)
def list_tool_runs(
    service: ToolServiceDependency, limit: int = 20
) -> ToolRunListResponse:
    return ToolRunListResponse(
        runs=[_tool_run_response(run) for run in service.list(limit=limit)]
    )


@router.get("/workflows/runs", response_model=WorkflowListResponse)
def list_workflow_runs(limit: int = 20) -> WorkflowListResponse:
    safe_limit = max(1, min(limit, 100))
    runs = [run.to_dict() for run in _workflow_store().list_runs(safe_limit)]
    return WorkflowListResponse(runs=[_workflow_summary(run) for run in runs])


@router.get("/workflows/runs/{run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(run_id: str) -> WorkflowRunResponse:
    run = _workflow_store().load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown workflow run: {run_id}")
    return WorkflowRunResponse(run=run.to_dict())


def _workflow_store():
    from src.workflows.store import WorkflowStore
    from src import api as _api
    return WorkflowStore(_api.WORKFLOW_DIR)


def _workflow_summary(run: dict):
    return {
        "run_id": run["run_id"],
        "workflow_name": run["workflow_name"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "elapsed_ms": run["elapsed_ms"],
        "event_count": len(run["events"]),
    }
