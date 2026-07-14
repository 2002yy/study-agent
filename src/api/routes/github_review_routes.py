"""Source-backed GitHub pull-request review-context endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.github import (
    GitHubPRReviewContextQueryRequest,
    GitHubSnapshotResultResponse,
)
from src.application.runtime_repository import get_github_pr_review_context_service
from src.web.github_cached_analysis import CachedGitHubPRReviewContextService

router = APIRouter(tags=["github-research"])
GitHubPRReviewContextServiceDependency = Annotated[
    CachedGitHubPRReviewContextService,
    Depends(get_github_pr_review_context_service),
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
    service: GitHubPRReviewContextServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.build(
        request.repo_url,
        request.number,
        max_files=request.max_files,
        max_symbols=request.max_symbols,
        max_comments=request.max_comments,
        max_reviews=request.max_reviews,
        depth=request.depth,
        max_impact_files=request.max_impact_files,
        max_edges=request.max_edges,
        max_provider_requests=request.max_provider_requests,
        max_pages_per_collection=request.max_pages_per_collection,
    )
    if result.get("ok") is not True:
        raise _http_error(result)
    return GitHubSnapshotResultResponse(result=result)
