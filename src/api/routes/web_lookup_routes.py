"""Durable WebLookupRun API plus recoverable ResearchRun aliases."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.news import (
    NewsLookupRequest,
    NewsLookupResponse,
    ResearchRunCreateRequest,
    WebLookupRunListResponse,
    WebLookupRunResponse,
)
from src.application.runtime_repository import get_web_lookup_service
from src.application.web_lookup_service import WebLookupService

router = APIRouter(tags=["web-lookup"])
WebLookupServiceDependency = Annotated[
    WebLookupService,
    Depends(get_web_lookup_service),
]


def _response(run) -> WebLookupRunResponse:
    return WebLookupRunResponse(**asdict(run))


def _not_found_or_conflict(exc: ValueError) -> HTTPException:
    message = str(exc)
    status = 404 if "not found" in message.lower() else 409
    return HTTPException(status_code=status, detail=message)


@router.post("/web-lookup-runs", response_model=WebLookupRunResponse)
def create_web_lookup_run(
    request: NewsLookupRequest,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    """Compatibility one-shot endpoint: create and immediately search."""
    try:
        return _response(service.lookup(request.query, max_items=request.max_items))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Web lookup failed: {exc}") from exc


@router.get("/web-lookup-runs", response_model=WebLookupRunListResponse)
def list_web_lookup_runs(
    service: WebLookupServiceDependency,
    limit: int = 20,
) -> WebLookupRunListResponse:
    return WebLookupRunListResponse(
        runs=[_response(run) for run in service.list(limit=limit)]
    )


@router.get("/web-lookup-runs/{run_id}", response_model=WebLookupRunResponse)
def get_web_lookup_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.get(run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/web-lookup-runs/{run_id}/retry", response_model=WebLookupRunResponse)
def retry_web_lookup_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.retry(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs", response_model=WebLookupRunResponse)
def create_research_run(
    request: ResearchRunCreateRequest,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.create(request.query, max_items=request.max_items))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/research-runs", response_model=WebLookupRunListResponse)
def list_research_runs(
    service: WebLookupServiceDependency,
    limit: int = 20,
) -> WebLookupRunListResponse:
    return list_web_lookup_runs(service=service, limit=limit)


@router.get("/research-runs/{run_id}", response_model=WebLookupRunResponse)
def get_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    return get_web_lookup_run(run_id=run_id, service=service)


@router.post("/research-runs/{run_id}/search", response_model=WebLookupRunResponse)
def search_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.search(run_id, raise_on_error=False))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/retry", response_model=WebLookupRunResponse)
def retry_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    return retry_web_lookup_run(run_id=run_id, service=service)


@router.post("/news/lookup", response_model=NewsLookupResponse, deprecated=True)
def lookup_news_compatibility_adapter(
    request: NewsLookupRequest,
    service: WebLookupServiceDependency,
) -> NewsLookupResponse:
    run = create_web_lookup_run(request, service)
    return NewsLookupResponse(
        run_id=run.id,
        query_text=run.query,
        news_items=run.items,
        source_block=run.source_block,
        warnings=run.warnings,
        status=run.status,
        stage=run.stage,
        empty_reason=run.empty_reason,
        attempts=run.attempts,
        error=run.error,
    )
