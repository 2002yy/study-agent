"""Tool and workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.models.common import ToolInvocationRequest, ToolInvocationResponse, ToolListResponse, WorkflowListResponse, WorkflowRunResponse

router = APIRouter(tags=["tools"])


@router.get("/tools", response_model=ToolListResponse)
def list_tools() -> ToolListResponse:
    from src.api.app import TOOL_REGISTRY

    return ToolListResponse(tools=[spec.to_dict() for spec in TOOL_REGISTRY.list_specs()])


@router.post("/tools/{tool_name}/preview", response_model=ToolInvocationResponse)
def preview_tool(tool_name: str, request: ToolInvocationRequest) -> ToolInvocationResponse:
    from src.api.app import TOOL_REGISTRY

    if TOOL_REGISTRY.get_spec(tool_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    result = TOOL_REGISTRY.preview(tool_name, request.args)
    return ToolInvocationResponse(**result.to_dict())


@router.post("/tools/{tool_name}/call", response_model=ToolInvocationResponse)
def call_tool(tool_name: str, request: ToolInvocationRequest) -> ToolInvocationResponse:
    from src.api.app import TOOL_REGISTRY

    if TOOL_REGISTRY.get_spec(tool_name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    result = TOOL_REGISTRY.call_with_audit(
        tool_name,
        request.args,
        store=_workflow_store(),
        run_id=request.run_id,
    )
    return ToolInvocationResponse(**result.to_dict())


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
