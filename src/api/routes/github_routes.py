"""Persistent GitHub snapshot, structure, impact, and history endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.github import (
    GitHubBlameQueryRequest,
    GitHubCommitQueryRequest,
    GitHubCompareQueryRequest,
    GitHubImpactQueryRequest,
    GitHubRefQueryRequest,
    GitHubSnapshotCreateRequest,
    GitHubSnapshotResultResponse,
    GitHubSnapshotRunListResponse,
    GitHubSnapshotRunResponse,
    GitHubStructureQueryRequest,
)
from src.application.github_graph_service import graph_service_for
from src.application.github_snapshot_service import GitHubSnapshotService
from src.application.runtime_repository import get_github_snapshot_service
from src.web.github_history import GitHubHistoryService

router = APIRouter(tags=["github-research"])
GitHubSnapshotServiceDependency = Annotated[
    GitHubSnapshotService,
    Depends(get_github_snapshot_service),
]
_history_service = GitHubHistoryService()


def get_github_history_service() -> GitHubHistoryService:
    return _history_service


GitHubHistoryServiceDependency = Annotated[
    GitHubHistoryService,
    Depends(get_github_history_service),
]


def _history_http_error(result: dict) -> HTTPException:
    status = str(result.get("status") or "")
    if status == "ambiguous":
        code = 409
    elif status in {"invalid", "invalid_ref", "unresolved_ref"}:
        code = 422
    elif status == "not_found":
        code = 404
    else:
        code = 502
    return HTTPException(
        status_code=code,
        detail={
            "error": str(result.get("error") or "GitHub history request failed"),
            "status": status,
            "result": result,
        },
    )


@router.post(
    "/github-repo-snapshots",
    response_model=GitHubSnapshotResultResponse,
)
def create_github_snapshot(
    request: GitHubSnapshotCreateRequest,
    service: GitHubSnapshotServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.snapshot(
        request.repo_url,
        query=request.query,
        ref=request.ref,
        force_refresh=request.force_refresh,
    )
    if result.get("ok") is not True:
        raise HTTPException(
            status_code=502,
            detail=str(result.get("error") or "GitHub snapshot failed"),
        )
    return GitHubSnapshotResultResponse(result=result)


@router.post(
    "/github-repo-structure",
    response_model=GitHubSnapshotResultResponse,
)
def inspect_github_structure(
    request: GitHubStructureQueryRequest,
    service: GitHubSnapshotServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = graph_service_for(service).inspect(
        request.repo_url,
        request.symbol,
        ref=request.ref,
        top_k=request.top_k,
    )
    if result.get("ok") is not True:
        status_code = 422 if result.get("error") == "empty_symbol" else 502
        raise HTTPException(
            status_code=status_code,
            detail=str(result.get("error") or "GitHub structure inspection failed"),
        )
    return GitHubSnapshotResultResponse(result=result)


@router.post(
    "/github-repo-impact",
    response_model=GitHubSnapshotResultResponse,
)
def inspect_github_impact(
    request: GitHubImpactQueryRequest,
    service: GitHubSnapshotServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = graph_service_for(service).impact(
        request.repo_url,
        request.symbol,
        ref=request.ref,
        depth=request.depth,
        max_files=request.max_files,
        max_edges=request.max_edges,
    )
    if result.get("ok") is not True:
        status_code = 422 if result.get("error") == "empty_symbol" else 502
        raise HTTPException(
            status_code=status_code,
            detail=str(result.get("error") or "GitHub impact inspection failed"),
        )
    return GitHubSnapshotResultResponse(result=result)


@router.post(
    "/github-ref",
    response_model=GitHubSnapshotResultResponse,
)
def resolve_github_ref(
    request: GitHubRefQueryRequest,
    service: GitHubHistoryServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.resolve_ref(request.repo_url, request.ref)
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post(
    "/github-commit",
    response_model=GitHubSnapshotResultResponse,
)
def inspect_github_commit(
    request: GitHubCommitQueryRequest,
    service: GitHubHistoryServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.commit(request.repo_url, request.ref)
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post(
    "/github-compare",
    response_model=GitHubSnapshotResultResponse,
)
def compare_github_refs(
    request: GitHubCompareQueryRequest,
    service: GitHubHistoryServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.compare(
        request.repo_url,
        request.base,
        request.head,
        max_files=request.max_files,
        max_patch_chars=request.max_patch_chars,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post(
    "/github-blame",
    response_model=GitHubSnapshotResultResponse,
)
def inspect_github_blame(
    request: GitHubBlameQueryRequest,
    service: GitHubHistoryServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.blame(
        request.repo_url,
        request.path,
        ref=request.ref,
        start_line=request.start_line,
        end_line=request.end_line,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.get(
    "/github-repo-snapshots",
    response_model=GitHubSnapshotRunListResponse,
)
def list_github_snapshots(
    service: GitHubSnapshotServiceDependency,
    limit: int = 20,
) -> GitHubSnapshotRunListResponse:
    return GitHubSnapshotRunListResponse(
        runs=[GitHubSnapshotRunResponse(**item) for item in service.list(limit=limit)]
    )


@router.get(
    "/github-repo-snapshots/{run_id}",
    response_model=GitHubSnapshotRunResponse,
)
def get_github_snapshot(
    run_id: str,
    service: GitHubSnapshotServiceDependency,
) -> GitHubSnapshotRunResponse:
    try:
        return GitHubSnapshotRunResponse(**service.get(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
