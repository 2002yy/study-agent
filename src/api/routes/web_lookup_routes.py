"""Durable WebLookupRun API plus recoverable ResearchRun aliases."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from src.api.models.news import (
    ResearchQueueRequest,
    ResearchQueueCompleteRequest,
    NewsLookupRequest,
    NewsLookupResponse,
    ResearchFollowUpCandidateResponse,
    ResearchRunCreateRequest,
    ResearchSteerRequest,
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
    """Compatibility one-shot endpoint: create and execute one research run."""

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
        return _response(
            service.create(
                request.query,
                max_items=request.max_items,
                owner_thread_id=request.owner_thread_id,
                parent_run_id=request.parent_run_id,
                create_request_id=request.create_request_id,
                suggestion_status=request.suggestion_status,
            )
        )
    except ValueError as exc:
        if request.parent_run_id:
            raise _not_found_or_conflict(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/sessions/{thread_id}/research-runs/follow-up-candidate",
    response_model=ResearchFollowUpCandidateResponse,
)
def get_research_follow_up_candidate(
    thread_id: str,
    query: str,
    service: WebLookupServiceDependency,
) -> ResearchFollowUpCandidateResponse:
    try:
        return ResearchFollowUpCandidateResponse(
            **service.follow_up_candidate(thread_id=thread_id, query=query)
        )
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.get("/research-runs", response_model=WebLookupRunListResponse)
def list_research_runs(
    service: WebLookupServiceDependency,
    limit: int = 20,
) -> WebLookupRunListResponse:
    return list_web_lookup_runs(service=service, limit=limit)


@router.get("/sessions/{thread_id}/research-queue")
def pending_research_followups(thread_id: str, service: WebLookupServiceDependency) -> dict:
    from src.api.routes.chat_routes import _research_progress

    progress = []
    for run in service.repository.list_by_owner_thread(thread_id, limit=100):
        owner = run.research_context.get("owner") or {}
        turn_id = owner.get("turn_id") if isinstance(owner, dict) else None
        if turn_id:
            progress.append({**_research_progress(run), "turn_id": turn_id})
    return {"messages": service.repository.pending_followups(thread_id), "progress": progress}


@router.post(
    "/research-runs/owners/turns/{turn_id}/cancel",
    response_model=WebLookupRunListResponse,
)
def cancel_research_runs_for_turn(
    turn_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunListResponse:
    try:
        return WebLookupRunListResponse(
            runs=[
                _response(run)
                for run in service.cancel_owned_by_turn(turn_id, wait_seconds=5.0)
            ]
        )
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.get("/research-runs/{run_id}", response_model=WebLookupRunResponse)
def get_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    return get_web_lookup_run(run_id=run_id, service=service)


@router.post("/research-runs/{run_id}/search", response_model=WebLookupRunResponse)
def execute_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.execute(run_id, raise_on_error=False))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/retry", response_model=WebLookupRunResponse)
def retry_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    return retry_web_lookup_run(run_id=run_id, service=service)


@router.post("/research-runs/{run_id}/resume", response_model=WebLookupRunResponse)
def resume_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.resume(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/cancel", response_model=WebLookupRunResponse)
def cancel_research_run(
    run_id: str,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    try:
        return _response(service.cancel(run_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/steer", response_model=WebLookupRunResponse)
def steer_research_run(
    run_id: str,
    request: ResearchSteerRequest,
    service: WebLookupServiceDependency,
) -> WebLookupRunResponse:
    """G18 decision 12: inject mid-run steering into an active deep-research run."""
    try:
        return _response(service.steer(run_id, content=request.content, request_id=request.request_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/queue", response_model=WebLookupRunResponse)
def queue_research_followup(run_id: str, request: ResearchQueueRequest, service: WebLookupServiceDependency) -> WebLookupRunResponse:
    try:
        return _response(service.repository.queue_followup(run_id, content=request.content, request_id=request.request_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/queue/{request_id}/complete", response_model=WebLookupRunResponse)
def complete_research_followup(run_id: str, request_id: str, request: ResearchQueueCompleteRequest, service: WebLookupServiceDependency) -> WebLookupRunResponse:
    try:
        return _response(service.repository.complete_followup(run_id, request_id=request_id, turn_id=request.turn_id))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


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
        provider_status=run.provider_status,
        stop_reason=run.stop_reason,
        query_attempts=run.query_attempts,
        error=run.error,
    )
