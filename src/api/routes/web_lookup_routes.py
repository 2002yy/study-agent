"""Durable WebLookupRun API plus recoverable ResearchRun aliases."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

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

# The stage feed reads what the run already persisted; it never advances or
# mutates the run. A reconnect costs no research and starts no send.
TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "partial", "failed", "cancelled"}
)
STEP_POLL_SECONDS = 0.05
STEP_IDLE_TIMEOUT_SECONDS = 300.0
STEP_HEARTBEAT_SECONDS = 10.0


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


def _run_steps(run) -> list[tuple[int, dict]]:
    deep = (run.research_context or {}).get("deep")
    steps = deep.get("steps") if isinstance(deep, dict) else None
    indexed: list[tuple[int, dict]] = []
    for position, step in enumerate(steps or []):
        if not isinstance(step, dict):
            continue
        try:
            seq = int(step.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        indexed.append((seq or position + 1, step))
    return indexed


@router.get("/research-runs/{run_id}/events")
async def stream_research_run_events(
    run_id: str,
    request: Request,
    service: WebLookupServiceDependency,
    after: int = Query(default=0, ge=0),
):
    """Follow one run's durable stage log, read-only.

    ``id`` on each frame is the step sequence. A client that reconnects sends
    that id back as ``Last-Event-ID`` and receives only later steps: the
    database is the cursor authority, so a dropped connection neither replays
    research nor starts a new send.
    """

    try:
        service.get(run_id)
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc

    cursor = [after]
    header_cursor = request.headers.get("last-event-id", "").strip()
    if header_cursor.isdigit():
        cursor[0] = int(header_cursor)

    async def frames() -> AsyncIterator[str]:
        idle = 0.0
        since_heartbeat = 0.0

        def idle_frame(status: str) -> str:
            return (
                "event: research_idle\ndata: "
                + json.dumps({"run_id": run_id, "status": status}, ensure_ascii=False)
                + "\n\n"
            )

        while True:
            try:
                run = service.get(run_id)
            except ValueError:
                yield idle_frame("unknown")
                return
            wrote = False
            for seq, step in _run_steps(run):
                if seq <= cursor[0]:
                    continue
                cursor[0] = seq
                payload = {
                    "run_id": run.id,
                    "seq": seq,
                    "kind": str(step.get("kind") or ""),
                    "text": str(step.get("text") or ""),
                    "at": str(step.get("at") or ""),
                }
                yield (
                    f"id: {seq}\nevent: research_step\ndata: "
                    f"{json.dumps(payload, ensure_ascii=False)}\n\n"
                )
                wrote = True
                idle = 0.0
                since_heartbeat = 0.0
            if run.status in TERMINAL_RUN_STATUSES and not wrote:
                yield idle_frame(run.status)
                return
            if await request.is_disconnected():
                return
            since_heartbeat += STEP_POLL_SECONDS
            if since_heartbeat >= STEP_HEARTBEAT_SECONDS:
                yield "event: heartbeat\ndata: {}\n\n"
                since_heartbeat = 0.0
            idle += STEP_POLL_SECONDS
            if idle >= STEP_IDLE_TIMEOUT_SECONDS:
                yield idle_frame(run.status)
                return
            await asyncio.sleep(STEP_POLL_SECONDS)

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        attachment_refs: list[dict] = []
        attachment_material: list[dict] = []
        if request.attachment_ids:
            run = service.get(run_id)
            from src.application.runtime_repository import get_session_attachment_service

            attachment_service = get_session_attachment_service()
            thread_id = run.owner_thread_id or ""
            _, problems = attachment_service.validate_selection(thread_id, request.attachment_ids)
            if problems:
                raise ValueError("附件不可用：" + "、".join(problems[:3]))
            attachment_refs = attachment_service.selection_refs(thread_id, request.attachment_ids)
            attachment_material = attachment_service.attachment_material(thread_id, request.attachment_ids)
        return _response(service.steer(
            run_id,
            content=request.content,
            request_id=request.request_id,
            attachment_refs=attachment_refs,
            attachment_material=attachment_material,
        ))
    except ValueError as exc:
        raise _not_found_or_conflict(exc) from exc


@router.post("/research-runs/{run_id}/queue", response_model=WebLookupRunResponse)
def queue_research_followup(run_id: str, request: ResearchQueueRequest, service: WebLookupServiceDependency) -> WebLookupRunResponse:
    try:
        attachment_refs: list[dict] = []
        if request.attachment_ids:
            from src.application.runtime_repository import get_session_attachment_service

            run = service.get(run_id)
            attachment_service = get_session_attachment_service()
            thread_id = run.owner_thread_id or ""
            selected_ids, problems = attachment_service.validate_selection(thread_id, request.attachment_ids)
            if problems:
                raise ValueError("附件不可用：" + "、".join(problems[:3]))
            attachment_refs = sorted(
                attachment_service.selection_refs(thread_id, request.attachment_ids),
                key=lambda item: item["attachment_id"],
            )
            if {ref["attachment_id"] for ref in attachment_refs} != set(selected_ids):
                raise ValueError("附件状态已变化，请重新选择")
        return _response(service.repository.queue_followup(
            run_id, content=request.content, request_id=request.request_id,
            attachment_refs=attachment_refs,
        ))
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
