"""Group chat endpoints backed by GroupChatService and SQLite."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from threading import Event
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.models.wechat import (
    WechatMessageRequest,
    WechatMessageResponse,
    WechatOpeningRequest,
    WechatSearchRequest,
    WechatSearchResponse,
    WechatStateResponse,
)
from src.application.group_chat_service import GroupChatService
from src.application.helpers import (
    request_model_profile,
    request_performance_mode,
    runtime_modes_for_request,
    sse_event,
    validate_choice,
)
from src.application.runtime_repository import get_group_service
from src.constants import ATMOS_OPTIONS, MODEL_OPTIONS, ROLE_OPTIONS

router = APIRouter(tags=["wechat"])
GroupServiceDependency = Annotated[GroupChatService, Depends(get_group_service)]


class _ClientDisconnected(Exception):
    pass


@router.get("/wechat", response_model=WechatStateResponse)
def get_wechat_state(
    service: GroupServiceDependency,
    group_thread_id: str | None = None,
) -> WechatStateResponse:
    try:
        return WechatStateResponse(**service.get_state(group_thread_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/wechat/reset", response_model=WechatStateResponse)
def reset_wechat_state_endpoint(
    service: GroupServiceDependency,
    group_thread_id: str | None = None,
) -> WechatStateResponse:
    try:
        created = service.reset(group_thread_id)
        return WechatStateResponse(**service.get_state(created.id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/wechat/mark-read", response_model=WechatStateResponse)
def mark_wechat_read_endpoint(
    service: GroupServiceDependency,
    group_thread_id: str | None = None,
    session_id: str | None = None,
) -> WechatStateResponse:
    target = group_thread_id or session_id
    try:
        thread = service.mark_read(target)
        return WechatStateResponse(**service.get_state(thread.id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/wechat/opening", response_model=WechatStateResponse)
def create_wechat_opening(
    request: WechatOpeningRequest,
    service: GroupServiceDependency,
) -> WechatStateResponse:
    validate_choice(request.selected_role, ROLE_OPTIONS, "selected_role")
    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
    try:
        thread = service.create_opening(
            thread_id=request.group_thread_id,
            role_hint=request.selected_role,
            relationship_mode=request.relationship_mode,
            performance_mode=request_performance_mode(request.performance_mode),
            selected_model=request.selected_model,
        )
        return WechatStateResponse(**service.get_state(thread.id))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/wechat/message", response_model=WechatMessageResponse)
def send_wechat_message(
    request: WechatMessageRequest,
    service: GroupServiceDependency,
) -> WechatMessageResponse:
    prepared = _prepare(request, service)
    reply = service.generate(prepared)
    state = service.get_state(prepared.thread.id)
    return WechatMessageResponse(
        reply=reply,
        content=state["content"],
        state=state["state"],
        session_id=prepared.thread.id,
        group_thread_id=prepared.thread.id,
        rag=prepared.rag,
        message_count=state["message_count"],
        unread_count=state["unread_count"],
        has_unread=state["has_unread"],
    )


@router.post("/wechat/message/stream")
async def send_wechat_message_stream(
    request: WechatMessageRequest,
    http_request: Request,
    service: GroupServiceDependency,
) -> StreamingResponse:
    prepared = _prepare(request, service)

    async def events() -> AsyncIterator[str]:
        reply_parts: list[str] = []
        cancel_event = Event()
        stream = service.stream_async(prepared, cancel_event=cancel_event)
        try:
            yield sse_event(
                "session",
                {
                    "group_thread_id": prepared.thread.id,
                    "message_id": prepared.message.id,
                    "operation_id": prepared.operation_id,
                },
            )
            yield sse_event("rag", prepared.rag)
            async for token in _tokens_until_disconnected(stream, http_request):
                reply_parts.append(token)
                yield sse_event("token", {"text": token})
            reply = service.complete(prepared, "".join(reply_parts))
            state = service.get_state(prepared.thread.id)
            yield sse_event(
                "done",
                {
                    "reply": reply,
                    "content": state["content"],
                    "state": state["state"],
                    "session_id": prepared.thread.id,
                    "group_thread_id": prepared.thread.id,
                    "rag": prepared.rag,
                    "message_count": state["message_count"],
                    "unread_count": state["unread_count"],
                    "has_unread": state["has_unread"],
                },
            )
        except _ClientDisconnected:
            cancel_event.set()
            with suppress(ValueError):
                service.interrupt(prepared, "".join(reply_parts))
            return
        except asyncio.CancelledError:
            cancel_event.set()
            with suppress(ValueError):
                service.interrupt(prepared, "".join(reply_parts))
            raise
        except Exception as exc:
            with suppress(ValueError):
                if reply_parts:
                    service.interrupt(prepared, "".join(reply_parts))
                else:
                    service.fail(prepared, str(exc))
            yield sse_event(
                "error", {"message": str(exc), "error_type": type(exc).__name__}
            )
        finally:
            cancel_event.set()
            with suppress(RuntimeError):
                await stream.aclose()
            current = service.repository.get_message(prepared.message.id)
            if current is not None and current.status == "streaming":
                with suppress(ValueError):
                    service.interrupt(prepared, "".join(reply_parts))

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
    """Poll disconnect state even while a synchronous provider awaits its first token."""

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


@router.post("/wechat/search", response_model=WechatSearchResponse)
def search_wechat_endpoint(
    request: WechatSearchRequest,
    service: GroupServiceDependency,
) -> WechatSearchResponse:
    try:
        results = service.search(
            request.group_thread_id, request.keyword, request.max_results
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return WechatSearchResponse(keyword=request.keyword, results=results)


def _prepare(request: WechatMessageRequest, service: GroupChatService):
    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
    runtime_modes = runtime_modes_for_request(request.performance_mode)
    model_profile = request_model_profile(
        request.selected_model, runtime_modes.performance_mode
    )
    try:
        return service.prepare_message(
            request.message,
            thread_id=request.group_thread_id or request.session_id,
            model_profile=model_profile,
            relationship_mode=request.relationship_mode,
            performance_mode=runtime_modes.performance_mode,
            rag_enabled=request.rag_enabled,
            rag_top_k=request.rag_chat_top_k or request.rag_top_k,
            rag_retrieval_mode=request.rag_retrieval_mode,
            rag_min_score=request.rag_min_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
