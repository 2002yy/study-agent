"""Source-backed GitHub pull-request review-context endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.github import (
    GitHubPRReviewContextQueryRequest,
    GitHubSnapshotResultResponse,
)
from src.api.routes.github_routes import (
    get_github_history_service,
    get_github_work_item_service,
)
from src.application.github_snapshot_service import GitHubSnapshotService
from src.application.runtime_repository import get_github_snapshot_service
from src.web.github_change_impact import GitHubChangeImpactService
from src.web.github_history import GitHubHistoryService
from src.web.github_pr_review_context import GitHubPRReviewContextService
from src.web.github_work_items import GitHubWorkItemService

router = APIRouter(tags=["github-research"])
GitHubSnapshotServiceDependency = Annotated[
    GitHubSnapshotService,
    Depends(get_github_snapshot_service),
]
GitHubHistoryServiceDependency = Annotated[
    GitHubHistoryService,
    Depends(get_github_history_service),
]
GitHubWorkItemServiceDependency = Annotated[
    GitHubWorkItemService,
    Depends(get_github_work_item_service),
]


def _http_error(result: dict) -> HTTPException:
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
            "error": str(result.get("error") or "GitHub review context failed"),
            "status": status,
            "result": result,
        },
    )


@router.post(
    "/github-pr-review-context",
    response_model=GitHubSnapshotResultResponse,
)
def inspect_github_pr_review_context(
    request: GitHubPRReviewContextQueryRequest,
    snapshot_service: GitHubSnapshotServiceDependency,
    history_service: GitHubHistoryServiceDependency,
    work_item_service: GitHubWorkItemServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = GitHubPRReviewContextService(
        work_item_service,
        GitHubChangeImpactService(history_service, snapshot_service),
    ).build(
        request.repo_url,
        request.number,
        max_files=request.max_files,
        max_symbols=request.max_symbols,
        max_comments=request.max_comments,
        max_reviews=request.max_reviews,
        depth=request.depth,
        max_impact_files=request.max_impact_files,
        max_edges=request.max_edges,
    )
    if result.get("ok") is not True:
        raise _http_error(result)
    return GitHubSnapshotResultResponse(result=result)
