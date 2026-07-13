"""Persistent GitHub repository snapshot endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.github import (
    GitHubSnapshotCreateRequest,
    GitHubSnapshotResultResponse,
    GitHubSnapshotRunListResponse,
    GitHubSnapshotRunResponse,
)
from src.application.github_snapshot_service import GitHubSnapshotService
from src.application.runtime_repository import get_github_snapshot_service

router = APIRouter(tags=["github-research"])
GitHubSnapshotServiceDependency = Annotated[
    GitHubSnapshotService,
    Depends(get_github_snapshot_service),
]


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
