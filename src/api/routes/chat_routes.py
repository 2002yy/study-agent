"""Thin HTTP/SSE adapters for the SQLite-backed chat application service."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.models.chat import (
    ChatRequest,
    ChatResponse,
    CommitTurnRequest,
    CommitTurnResponse,
)
from src.application.chat_service import ChatService
from src.application.helpers import sse_event, stream_usage_payload
from src.application.policy_chat_service import PolicyChatCommand
from src.application.runtime_repository import get_chat_service, get_web_lookup_service
from src.application.web_lookup_service import WebLookupService

router = APIRouter(tags=["chat"])
ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]
WebLookupServiceDependency = Annotated[
    WebLookupService,
    Depends(get_web_lookup_service),
]


class _ClientDisconnected(Exception):
    pass


def pedagogy_summary_from_plan(plan: Any) -> dict[str, Any]:
    """Compact pedagogy snapshot for the chat response (decision point a)."""
    return {
        "mode": str(getattr(plan, "mode", "") or ""),
        "phase": str(getattr(plan, "phase", "") or ""),
        "move": str(getattr(plan, "move", "") or ""),
        "disclosure_level": int(getattr(plan, "disclosure_level", 0) or 0),
    }


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    service: ChatServiceDependency,
    research_service: WebLookupServiceDependency,
) -> ChatResponse:
    try:
        prepared = service.start_turn(_chat_command(request, research_service))
        reply = service.generate(prepared)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ChatResponse(
        reply=reply,
        session_id=prepared.thread.id,
        turn_id=prepared.turn.id,
        route=prepared.route,
        rag=prepared.rag,
        pedagogy=pedagogy_summary_from_plan(prepared.pedagogy_plan),
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(
    chat_request: ChatRequest,
    http_request: Request,
    service: ChatServiceDependency,
    research_service: WebLookupServiceDependency,
) -> StreamingResponse:
    try:
        command = _chat_command(chat_request, research_service)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def events() -> AsyncIterator[str]:
        prepared = None
        prepare_task = asyncio.create_task(
            asyncio.to_thread(service.start_turn, command)
        )
        observed_research_version: tuple[str, int] | None = None

        while not prepare_task.done():
            if chat_request.turn_id and await http_request.is_disconnected():
                await asyncio.to_thread(
                    research_service.cancel_owned_by_turn,
                    chat_request.turn_id,
                    wait_seconds=0.0,
                )
                _settle_disconnected_preparation(prepare_task, service)
                return
            run = (
                await asyncio.to_thread(
                    research_service.latest_owned_by_turn,
                    chat_request.turn_id,
                )
                if chat_request.turn_id
                else None
            )
            if run is not None and observed_research_version != (run.id, run.version):
                observed_research_version = (run.id, run.version)
                yield sse_event("research", _research_progress(run))
            await asyncio.wait({prepare_task}, timeout=0.05)

        try:
            prepared = prepare_task.result()
        except Exception as exc:
            yield sse_event(
                "error",
                {"message": str(exc), "error_type": type(exc).__name__},
            )
            return

        run = await asyncio.to_thread(
            research_service.latest_owned_by_turn,
            prepared.turn.id,
        )
        if run is not None and observed_research_version != (run.id, run.version):
            yield sse_event("research", _research_progress(run))

        reply_parts: list[str] = []
        stream = service.stream_async(prepared)

        try:
            yield sse_event(
                "session",
                {
                    "session_id": prepared.thread.id,
                    "turn_id": prepared.turn.id,
                    "operation_id": prepared.turn.operation_id,
                },
            )
            yield sse_event("route", prepared.route)
            yield sse_event("rag", prepared.rag)
            async for token in _tokens_until_disconnected(stream, http_request):
                reply_parts.append(token)
                yield sse_event("token", {"text": token})
            suffix = "".join(reply_parts)
            completed = service.complete_turn(prepared, suffix)
            yield sse_event("usage", stream_usage_payload(completed.assistant_message))
            yield sse_event(
                "done",
                {
                    "session_id": prepared.thread.id,
                    "turn_id": prepared.turn.id,
                    "reply": completed.assistant_message,
                    "pedagogy": pedagogy_summary_from_plan(prepared.pedagogy_plan),
                },
            )
        except _ClientDisconnected:
            with suppress(ValueError):
                service.interrupt_turn(prepared, "".join(reply_parts))
            return
        except asyncio.CancelledError:
            with suppress(ValueError):
                service.interrupt_turn(prepared, "".join(reply_parts))
            raise
        except Exception as exc:
            with suppress(ValueError):
                service.interrupt_turn(prepared, "".join(reply_parts))
            yield sse_event(
                "error",
                {"message": str(exc), "error_type": type(exc).__name__},
            )
        finally:
            with suppress(RuntimeError):
                await stream.aclose()
            current = service.repository.get_chat_turn(prepared.turn.id)
            if current is not None and current.status == "streaming":
                with suppress(ValueError):
                    service.interrupt_turn(prepared, "".join(reply_parts))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _research_progress(run: Any) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "stage": run.stage,
        "provider_status": run.provider_status,
        "stop_reason": run.stop_reason,
        "error": run.error,
        "query_attempt_count": len(run.query_attempts),
        "selected_source_count": len(run.selected_sources),
        "version": run.version,
    }


def _settle_disconnected_preparation(
    prepare_task: asyncio.Task[Any],
    service: ChatService,
) -> None:
    async def settle() -> None:
        try:
            prepared = await prepare_task
        except Exception:
            return
        with suppress(ValueError):
            service.interrupt_turn(prepared, "")

    asyncio.create_task(settle())


async def _tokens_until_disconnected(
    stream: AsyncIterator[str],
    request: Request,
    *,
    poll_interval: float = 0.05,
) -> AsyncIterator[str]:
    """Wait for provider tokens while keeping client disconnects observable."""

    while True:
        next_token = asyncio.create_task(anext(stream))
        try:
            while not next_token.done():
                done, _ = await asyncio.wait({next_token}, timeout=poll_interval)
                if done:
                    break
                if await request.is_disconnected():
                    next_token.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_token
                    raise _ClientDisconnected
            try:
                yield next_token.result()
            except StopAsyncIteration:
                return
        finally:
            if not next_token.done():
                next_token.cancel()
                with suppress(asyncio.CancelledError):
                    await next_token


@router.post(
    "/sessions/{session_id}/commit-turn",
    response_model=CommitTurnResponse,
)
def commit_turn_endpoint(
    session_id: str,
    request: CommitTurnRequest,
    service: ChatServiceDependency,
) -> CommitTurnResponse:
    if not request.turn_id:
        raise HTTPException(status_code=400, detail="turn_id is required")
    try:
        _, changed = service.commit_partial_turn(
            thread_id=session_id,
            turn_id=request.turn_id,
            operation_id=request.operation_id,
            user_input=request.user_input,
            assistant_message=request.agent_reply,
            role=request.role,
            mode=request.mode,
            model=request.model,
            route_snapshot=request.route_info,
            rag_snapshot=request.rag_info,
            conversation_instruction=request.conversation_instruction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return CommitTurnResponse(
        session_id=session_id,
        committed=changed,
        message="ok" if changed else "already committed",
    )


@router.post("/sessions/{session_id}/turns/{turn_id}/abandon")
def abandon_interrupted_turn_endpoint(
    session_id: str,
    turn_id: str,
    service: ChatServiceDependency,
) -> dict[str, Any]:
    thread = service.repository.get_chat_thread(session_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Session not found")
    turn = service.repository.get_chat_turn(turn_id)
    if turn is None or turn.thread_id != session_id:
        raise HTTPException(status_code=404, detail="Chat turn not found")
    if turn.status == "abandoned":
        return {
            "session_id": session_id,
            "turn_id": turn_id,
            "status": "abandoned",
            "changed": False,
        }
    if turn.status not in {"interrupted", "failed"}:
        raise HTTPException(
            status_code=409,
            detail=f"Chat turn cannot be abandoned from status {turn.status}",
        )
    updated = service.repository.update_chat_turn(
        turn_id,
        assistant_message=turn.assistant_message,
        status="abandoned",
        expected_status=turn.status,
    )
    if updated is None:
        raise HTTPException(status_code=409, detail="Chat turn state changed")
    return {
        "session_id": session_id,
        "turn_id": turn_id,
        "status": updated.status,
        "changed": True,
    }


def _chat_command(
    request: ChatRequest,
    research_service: WebLookupService | None = None,
) -> PolicyChatCommand:
    web_context = request.web_context
    web_context_run_id = request.web_context_run_id
    if web_context_run_id:
        if research_service is None:
            raise ValueError("ResearchRun validation service is required")
        run = research_service.get(web_context_run_id)
        if run.status not in {"completed", "partial"} or not run.source_block.strip():
            raise ValueError(f"ResearchRun is not usable as chat evidence: {run.id}")
        if web_context.strip() != run.source_block.strip():
            raise ValueError(f"ResearchRun source block does not match: {run.id}")
        web_context = run.source_block
        web_context_run_id = run.id
    return PolicyChatCommand(
        user_input=request.user_input,
        selected_role=request.selected_role,
        selected_mode=request.selected_mode,
        selected_model=request.selected_model,
        relationship_mode=request.relationship_mode,
        scene=request.scene,
        conversation_instruction=request.conversation_instruction,
        performance_mode=request.performance_mode,
        context_mode=request.context_mode,
        previous_mode=request.previous_mode,
        chat_history=[message.model_dump() for message in request.chat_history],
        keep_current_role=request.keep_current_role,
        thread_id=request.session_id,
        rag_enabled=request.rag_enabled,
        rag_top_k=request.rag_top_k,
        rag_search_top_k=request.rag_search_top_k,
        rag_chat_top_k=request.rag_chat_top_k,
        rag_retrieval_mode=request.rag_retrieval_mode,
        rag_min_score=request.rag_min_score,
        web_context=web_context,
        web_context_run_id=web_context_run_id,
        web_policy=request.web_policy,
        web_consent=request.web_consent,
        cloud_context_policy=request.cloud_context_policy,
        task_intent=request.task_intent,
        continuation_of_turn_id=request.continuation_of_turn_id,
        retry_of_turn_id=request.retry_of_turn_id,
        partial_reply=request.partial_reply,
        turn_id=request.turn_id,
    )
