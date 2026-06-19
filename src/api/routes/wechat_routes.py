"""Wechat (group chat) endpoints — state, opening, messages, search."""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.models.wechat import (
    WechatMessageRequest,
    WechatMessageResponse,
    WechatOpeningRequest,
    WechatSearchRequest,
    WechatSearchResponse,
    WechatStateResponse,
)
from src.constants import ATMOS_OPTIONS, MODEL_OPTIONS, ROLE_OPTIONS
from src.application.helpers import (
    request_model_profile,
    request_performance_mode,
    runtime_modes_for_request,
    sse_event,
    validate_choice,
    wechat_state_payload,
)

router = APIRouter(tags=["wechat"])


@router.get("/wechat", response_model=WechatStateResponse)
def get_wechat_state() -> WechatStateResponse:
    return wechat_state_payload()


@router.post("/wechat/reset", response_model=WechatStateResponse)
def reset_wechat_state_endpoint() -> WechatStateResponse:
    from src.api import reset_wechat_group

    reset_wechat_group()
    return wechat_state_payload()


@router.post("/wechat/mark-read", response_model=WechatStateResponse)
def mark_wechat_read_endpoint(session_id: str | None = None) -> WechatStateResponse:
    from src.api import mark_wechat_read, set_wechat_unread_cleared

    mark_wechat_read()
    if session_id:
        set_wechat_unread_cleared(session_id)
    return wechat_state_payload()


@router.post("/wechat/opening", response_model=WechatStateResponse)
def create_wechat_opening(request: WechatOpeningRequest) -> WechatStateResponse:
    from src.api import (
        generate_wechat_opening,
        has_wechat_group_started,
        start_wechat_group_with_opening,
    )

    validate_choice(request.selected_role, ROLE_OPTIONS, "selected_role")
    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")

    if has_wechat_group_started():
        raise HTTPException(
            status_code=409,
            detail=(
                "群聊已有历史内容。生成开场会覆盖当前群聊。"
                "如需重新开始，请先使用「新群聊」（会归档旧内容），再生成开场。"
            ),
        )

    performance_mode = request_performance_mode(request.performance_mode)
    opening = generate_wechat_opening(
        role_hint=request.selected_role,
        relationship_mode=request.relationship_mode,
        performance_mode=performance_mode,
        selected_model=request.selected_model,
    )
    start_wechat_group_with_opening(opening)
    return wechat_state_payload()


@router.post("/wechat/message", response_model=WechatMessageResponse)
def send_wechat_message(request: WechatMessageRequest) -> WechatMessageResponse:
    from src.api import (
        append_user_and_interactive_group_reply,
        count_wechat_messages,
        generate_interactive_wechat_reply,
        init_session,
        read_wechat_group,
        read_wechat_state,
        retrieve_local_knowledge,
        set_wechat_interactive,
        set_wechat_status,
        update_wechat_join_state,
    )

    validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
    validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
    runtime_modes = runtime_modes_for_request(request.performance_mode)
    model_profile = request_model_profile(request.selected_model, runtime_modes.performance_mode)
    rag_result = retrieve_local_knowledge(
        request.message,
        enabled=request.rag_enabled,
        top_k=request.rag_chat_top_k or request.rag_top_k,
        retrieval_mode=request.rag_retrieval_mode,
        min_score=request.rag_min_score,
    )
    reply = generate_interactive_wechat_reply(
        request.message,
        model_profile=model_profile,
        relationship_mode=request.relationship_mode,
        rag_context=rag_result.context,
        performance_mode=runtime_modes.performance_mode,
        session_id=request.session_id,
    )
    append_user_and_interactive_group_reply(request.message, reply)
    update_wechat_join_state(
        user_has_joined=True,
        first_reaction_done=True,
        mode="interactive_group",
    )
    session_id = request.session_id or init_session()
    set_wechat_interactive(session_id, "generated")
    set_wechat_status(session_id, "interactive_group")
    return WechatMessageResponse(
        reply=reply,
        content=read_wechat_group(),
        state=read_wechat_state(),
        session_id=session_id,
        rag=rag_result.to_dict(),
        message_count=count_wechat_messages(read_wechat_group()),
    )


@router.post("/wechat/message/stream")
async def send_wechat_message_stream(request: WechatMessageRequest, http_request: Request) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        disconnected = False

        def should_cancel() -> bool:
            return disconnected

        reply_parts: list[str] = []
        try:
            from src.api import (
                append_user_and_interactive_group_reply,
                count_wechat_messages,
                generate_interactive_wechat_reply_stream,
                init_session,
                read_wechat_group,
                read_wechat_state,
                retrieve_local_knowledge,
                set_wechat_interactive,
                set_wechat_status,
                update_wechat_join_state,
            )

            validate_choice(request.selected_model, MODEL_OPTIONS, "selected_model")
            validate_choice(request.relationship_mode, ATMOS_OPTIONS, "relationship_mode")
            runtime_modes = runtime_modes_for_request(request.performance_mode)
            model_profile = request_model_profile(request.selected_model, runtime_modes.performance_mode)
            rag_result = retrieve_local_knowledge(
                request.message,
                enabled=request.rag_enabled,
                top_k=request.rag_chat_top_k or request.rag_top_k,
                retrieval_mode=request.rag_retrieval_mode,
                min_score=request.rag_min_score,
            )
            yield sse_event("rag", rag_result.to_dict())
            stream, _is_first = generate_interactive_wechat_reply_stream(
                request.message,
                model_profile=model_profile,
                relationship_mode=request.relationship_mode,
                rag_context=rag_result.context,
                performance_mode=runtime_modes.performance_mode,
                should_cancel=should_cancel,
                session_id=request.session_id,
            )
            for token in stream:
                if await http_request.is_disconnected():
                    disconnected = True
                    return
                reply_parts.append(token)
                yield sse_event("token", {"text": token})
            reply = "".join(reply_parts).strip()
            append_user_and_interactive_group_reply(request.message, reply)
            update_wechat_join_state(
                user_has_joined=True,
                first_reaction_done=True,
                mode="interactive_group",
            )
            session_id = request.session_id or init_session()
            set_wechat_interactive(session_id, "generated")
            set_wechat_status(session_id, "interactive_group")
            yield sse_event(
                "done",
                {
                    "reply": reply,
                    "content": read_wechat_group(),
                    "state": read_wechat_state(),
                    "session_id": session_id,
                    "rag": rag_result.to_dict(),
                    "message_count": count_wechat_messages(read_wechat_group()),
                },
            )
        except Exception as exc:
            yield sse_event("error", {"message": str(exc), "error_type": type(exc).__name__})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/wechat/search", response_model=WechatSearchResponse)
def search_wechat_endpoint(request: WechatSearchRequest) -> WechatSearchResponse:
    from src.api import search_wechat

    return WechatSearchResponse(
        keyword=request.keyword,
        results=search_wechat(request.keyword, max_results=request.max_results),
    )
