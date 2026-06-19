"""Chat endpoints — single-chat, streaming, and commit-turn."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.api.models.chat import (
    ChatRequest,
    ChatResponse,
    CommitTurnRequest,
    CommitTurnResponse,
)
from src.application.helpers import (
    prepare_chat_context,
    sse_event,
    stream_usage_payload,
)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest) -> ChatResponse:
    from src.api import chat, chat_max_tokens, flush_current_session, init_session, log

    prepared = prepare_chat_context(request)
    runtime_modes = prepared["runtime_modes"]
    route = prepared["route"]
    rag_result = prepared["rag_result"]
    reply = chat(
        prepared["messages"],
        model_profile=route["model_profile"],
        max_tokens=chat_max_tokens(runtime_modes.performance_mode),
        task_name="single_chat",
    )
    session_id = request.session_id or init_session()
    log(
        session_id=session_id,
        role=route["role"],
        mode=route["mode"],
        model=route["model_profile"],
        user_input=request.user_input,
        agent_reply=reply,
        memory_enabled=bool(prepared["memory_bundle"]),
        route_info={
            **route,
            "rag_status": rag_result.status,
            "web_context_used": prepared["web_context_used"],
            "is_continuation": prepared["is_continuation"],
        },
        session_settings=prepared["session_settings"],
        rag_info=rag_result.to_dict(),
        conversation_instruction=request.conversation_instruction,
    )
    flush_current_session(
        session_id,
        performance_mode=runtime_modes.performance_mode,
        debug_mode=runtime_modes.debug_mode,
    )
    return ChatResponse(
        reply=reply,
        session_id=session_id,
        route=route,
        rag=rag_result.to_dict(),
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(chat_request: ChatRequest, http_request: Request) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        from src.api import (
            chat_max_tokens,
            flush_current_session,
            init_session,
            log,
            stream_chat,
        )

        session_id = chat_request.session_id or init_session()
        reply_parts: list[str] = []
        disconnected = False

        def should_cancel() -> bool:
            return disconnected

        try:
            prepared = prepare_chat_context(chat_request)
            runtime_modes = prepared["runtime_modes"]
            route = prepared["route"]
            rag_result = prepared["rag_result"]
            yield sse_event("session", {"session_id": session_id})
            yield sse_event("route", route)
            yield sse_event("rag", rag_result.to_dict())
            for token in stream_chat(
                prepared["messages"],
                model_profile=route["model_profile"],
                max_tokens=chat_max_tokens(runtime_modes.performance_mode),
                task_name="single_chat",
                should_cancel=should_cancel,
            ):
                if await http_request.is_disconnected():
                    disconnected = True
                    return
                reply_parts.append(token)
                yield sse_event("token", {"text": token})
            reply = "".join(reply_parts)
            yield sse_event("usage", stream_usage_payload(reply))
            log(
                session_id=session_id,
                role=route["role"],
                mode=route["mode"],
                model=route["model_profile"],
                user_input=chat_request.user_input,
                agent_reply=reply,
                memory_enabled=bool(prepared["memory_bundle"]),
                route_info={
                    **route,
                    "rag_status": rag_result.status,
                    "web_context_used": prepared["web_context_used"],
                    "streamed": True,
                    "is_continuation": prepared["is_continuation"],
                    "is_continuation_resolved": bool(chat_request.turn_id),
                },
                session_settings=prepared["session_settings"],
                rag_info=rag_result.to_dict(),
                conversation_instruction=chat_request.conversation_instruction,
                turn_id=chat_request.turn_id or None,
                merge_with_existing=bool(chat_request.continuation_of_turn_id and chat_request.turn_id),
            )
            flush_current_session(
                session_id,
                performance_mode=runtime_modes.performance_mode,
                debug_mode=runtime_modes.debug_mode,
            )
            yield sse_event("done", {"session_id": session_id, "reply": reply})
        except Exception as exc:
            yield sse_event("error", {"message": str(exc), "error_type": type(exc).__name__})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/commit-turn", response_model=CommitTurnResponse)
def commit_turn_endpoint(session_id: str, request: CommitTurnRequest) -> CommitTurnResponse:
    """Commit a partial/incomplete turn (e.g. interrupted stream) to the session log.

    This allows the frontend to persist a partially-streamed reply before
    the normal log() call at chat completion time.
    """
    from src.api import get_or_create_session, log

    sess = get_or_create_session(session_id)
    # Only log if no entry exists for this exact input yet (idempotent)
    existing = sess.get("entries", [])
    already_logged = any(
        e.get("user") == request.user_input and e.get("agent") == request.agent_reply
        for e in existing
    )
    if not already_logged:
        log(
            session_id=session_id,
            role=request.role,
            mode=request.mode,
            model=request.model,
            user_input=request.user_input,
            agent_reply=request.agent_reply,
            memory_enabled=request.memory_enabled,
            route_info=request.route_info,
            rag_info=request.rag_info,
            conversation_instruction=request.conversation_instruction,
            turn_id=request.turn_id,
        )
    return CommitTurnResponse(session_id=session_id, committed=not already_logged, message="ok" if not already_logged else "already committed")
