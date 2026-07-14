"""Persistent GitHub source, history, work-item, CI, and change-impact endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.github import (
    GitHubBlameQueryRequest,
    GitHubCILogsQueryRequest,
    GitHubChangeImpactQueryRequest,
    GitHubChecksQueryRequest,
    GitHubCommitQueryRequest,
    GitHubCompareQueryRequest,
    GitHubImpactQueryRequest,
    GitHubIssueQueryRequest,
    GitHubPullRequestQueryRequest,
    GitHubRefQueryRequest,
    GitHubSnapshotCreateRequest,
    GitHubSnapshotResultResponse,
    GitHubSnapshotRunListResponse,
    GitHubSnapshotRunResponse,
    GitHubStructureQueryRequest,
)
from src.application.github_graph_service import graph_service_for
from src.application.github_snapshot_service import GitHubSnapshotService
from src.application.runtime_repository import (
    get_github_change_impact_service,
    get_github_history_service,
    get_github_research_cache_repository,
    get_github_snapshot_service,
    get_github_work_item_service,
)
from src.repositories.github_research_cache_repository import (
    GitHubResearchCacheRepository,
)
from src.web.github_cached_analysis import CachedGitHubChangeImpactService
from src.web.github_cached_work_items import PersistentGitHubWorkItemService
from src.web.github_history import GitHubHistoryService

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
    PersistentGitHubWorkItemService,
    Depends(get_github_work_item_service),
]
GitHubChangeImpactServiceDependency = Annotated[
    CachedGitHubChangeImpactService,
    Depends(get_github_change_impact_service),
]
GitHubResearchCacheDependency = Annotated[
    GitHubResearchCacheRepository,
    Depends(get_github_research_cache_repository),
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
            "error": str(result.get("error") or "GitHub request failed"),
            "status": status,
            "result": result,
        },
    )


@router.post("/github-repo-snapshots", response_model=GitHubSnapshotResultResponse)
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


@router.post("/github-repo-structure", response_model=GitHubSnapshotResultResponse)
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


@router.post("/github-repo-impact", response_model=GitHubSnapshotResultResponse)
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


@router.post("/github-ref", response_model=GitHubSnapshotResultResponse)
def resolve_github_ref(
    request: GitHubRefQueryRequest,
    service: GitHubHistoryServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.resolve_ref(request.repo_url, request.ref)
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post("/github-commit", response_model=GitHubSnapshotResultResponse)
def inspect_github_commit(
    request: GitHubCommitQueryRequest,
    service: GitHubHistoryServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.commit(request.repo_url, request.ref)
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post("/github-compare", response_model=GitHubSnapshotResultResponse)
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


@router.post("/github-change-impact", response_model=GitHubSnapshotResultResponse)
def inspect_github_change_impact(
    request: GitHubChangeImpactQueryRequest,
    service: GitHubChangeImpactServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.analyze(
        request.repo_url,
        request.base,
        request.head,
        max_files=request.max_files,
        max_symbols=request.max_symbols,
        depth=request.depth,
        max_impact_files=request.max_impact_files,
        max_edges=request.max_edges,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post("/github-blame", response_model=GitHubSnapshotResultResponse)
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


@router.post("/github-pr", response_model=GitHubSnapshotResultResponse)
def inspect_github_pull_request(
    request: GitHubPullRequestQueryRequest,
    service: GitHubWorkItemServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.pull_request(
        request.repo_url,
        request.number,
        max_files=request.max_files,
        max_patch_chars=request.max_patch_chars,
        max_comments=request.max_comments,
        max_reviews=request.max_reviews,
        include_checks=request.include_checks,
        max_provider_requests=request.max_provider_requests,
        max_pages_per_collection=request.max_pages_per_collection,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post("/github-issue", response_model=GitHubSnapshotResultResponse)
def inspect_github_issue(
    request: GitHubIssueQueryRequest,
    service: GitHubWorkItemServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.issue(
        request.repo_url,
        request.number,
        max_comments=request.max_comments,
        max_events=request.max_events,
        max_provider_requests=request.max_provider_requests,
        max_pages_per_collection=request.max_pages_per_collection,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post("/github-checks", response_model=GitHubSnapshotResultResponse)
def inspect_github_checks(
    request: GitHubChecksQueryRequest,
    service: GitHubWorkItemServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.checks(
        request.repo_url,
        ref=request.ref,
        max_runs=request.max_runs,
        max_checks=request.max_checks,
        max_jobs=request.max_jobs,
        include_jobs=request.include_jobs,
        max_provider_requests=request.max_provider_requests,
        max_pages_per_collection=request.max_pages_per_collection,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.post("/github-ci-logs", response_model=GitHubSnapshotResultResponse)
def inspect_github_ci_logs(
    request: GitHubCILogsQueryRequest,
    service: GitHubWorkItemServiceDependency,
) -> GitHubSnapshotResultResponse:
    result = service.ci_logs(
        request.repo_url,
        request.job_id,
        max_chars=request.max_chars,
        max_lines=request.max_lines,
    )
    if result.get("ok") is not True:
        raise _history_http_error(result)
    return GitHubSnapshotResultResponse(result=result)


@router.get("/github-research-cache", response_model=GitHubSnapshotResultResponse)
def inspect_github_research_cache(
    service: GitHubResearchCacheDependency,
) -> GitHubSnapshotResultResponse:
    return GitHubSnapshotResultResponse(result=service.manifest())


@router.delete("/github-research-cache", response_model=GitHubSnapshotResultResponse)
def clear_github_research_cache(
    service: GitHubResearchCacheDependency,
    repository: str = "",
    cache_kind: str = "",
    expired_only: bool = False,
) -> GitHubSnapshotResultResponse:
    deleted = (
        service.delete_expired()
        if expired_only
        else service.clear(repository=repository, cache_kind=cache_kind)
    )
    return GitHubSnapshotResultResponse(
        result={
            "ok": True,
            "deleted": deleted,
            "expired_only": expired_only,
            "repository": repository,
            "cache_kind": cache_kind,
            "manifest": service.manifest(),
        }
    )


@router.get("/github-repo-snapshots", response_model=GitHubSnapshotRunListResponse)
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
