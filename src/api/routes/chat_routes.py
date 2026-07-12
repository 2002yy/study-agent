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
from src.application.chat_service import ChatCommand, ChatService
from src.application.helpers import sse_event, stream_usage_payload
from src.application.runtime_repository import get_chat_service

router = APIRouter(tags=["chat"])
ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]


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
def chat_endpoint(request: ChatRequest, service: ChatServiceDependency) -> ChatResponse:
    try:
        prepared = service.start_turn(_chat_command(request))
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
) -> StreamingResponse:
    try:
        prepared = service.start_turn(_chat_command(chat_request))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def events() -> AsyncIterator[str]:
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


def _chat_command(request: ChatRequest) -> ChatCommand:
    return ChatCommand(
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
        web_context=request.web_context,
        continuation_of_turn_id=request.continuation_of_turn_id,
        retry_of_turn_id=request.retry_of_turn_id,
        partial_reply=request.partial_reply,
        turn_id=request.turn_id,
    )
