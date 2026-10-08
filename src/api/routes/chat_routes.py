"""Thin HTTP/SSE adapters for the SQLite-backed chat application service."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.models.chat import (
    CancelTurnRequest,
    CancelTurnResponse,
    ChatRequest,
    ChatResponse,
    CommitTurnRequest,
    CommitTurnResponse,
    TurnStatusResponse,
)
from src.application.chat_service import (
    ChatService,
    TurnCancelled,
    answer_validation_active,
)
from src.application.helpers import sse_event, stream_usage_payload
from src.application.policy_chat_service import PolicyChatCommand
from src.application.research_evidence import (
    research_binding_rows,
    research_run_provenance,
    research_sources_snapshot,
)
from src.application.research_presentation import (
    research_presentation,
    research_run_event,
)
from src.application.runtime_repository import (
    get_chat_service,
    get_session_service,
    get_web_lookup_service,
)
from src.application.session_service import SessionService
from src.application.web_lookup_service import WebLookupService

router = APIRouter(tags=["chat"])
ChatServiceDependency = Annotated[ChatService, Depends(get_chat_service)]
WebLookupServiceDependency = Annotated[
    WebLookupService,
    Depends(get_web_lookup_service),
]
SessionServiceDependency = Annotated[SessionService, Depends(get_session_service)]


@router.get("/sessions/{thread_id}/turns/{turn_id}/research-presentation")
def get_research_presentation(
    thread_id: str,
    turn_id: str,
    service: ChatServiceDependency,
    research_service: WebLookupServiceDependency,
) -> dict[str, Any]:
    turn = service.repository.get_chat_turn(turn_id)
    if turn is None or turn.thread_id != thread_id:
        raise HTTPException(status_code=404, detail="Chat turn not found")
    return research_presentation(
        turn, research_service.repository.list_by_owner_turn(turn_id, limit=100)
    )


def _drain_queued_archive(
    session_service: SessionService | None, thread_id: str | None
) -> None:
    """Best-effort execution of a persisted "archive after cancel" intent."""
    if session_service is None or not thread_id:
        return
    with suppress(Exception):
        session_service.execute_queued_archive_if_due(thread_id)


class _ClientDisconnected(Exception):
    pass


class _TurnCancelled(Exception):
    """Signals that a turn cancellation was observed during streaming."""

    def __init__(self, turn_id: str, operation_id: str) -> None:
        super().__init__(f"Turn cancelled during streaming: {turn_id}")
        self.turn_id = turn_id
        self.operation_id = operation_id


def pedagogy_summary_from_plan(plan: Any) -> dict[str, Any]:
    """Compact pedagogy snapshot for the chat response (decision point a)."""
    raw_ids = getattr(plan, "evidence_ids", ()) or ()
    return {
        "mode": str(getattr(plan, "mode", "") or ""),
        "phase": str(getattr(plan, "phase", "") or ""),
        "move": str(getattr(plan, "move", "") or ""),
        "disclosure_level": int(getattr(plan, "disclosure_level", 0) or 0),
        "evidence_ids": [str(eid) for eid in raw_ids],
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
    except TurnCancelled as exc:
        raise HTTPException(
            status_code=499,
            detail={
                "message": "Chat turn cancelled",
                "turn_id": exc.turn_id,
                "operation_id": exc.operation_id,
                "stage": exc.stage,
            },
        ) from exc
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
    session_service: SessionServiceDependency,
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
                yield sse_event("research_presentation", research_run_event(run))
            await asyncio.wait({prepare_task}, timeout=0.05)

        try:
            prepared = prepare_task.result()
        except TurnCancelled as exc:
            yield sse_event(
                "cancelled",
                {
                    "turn_id": exc.turn_id,
                    "operation_id": exc.operation_id,
                    "stage": exc.stage,
                },
            )
            return
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
            yield sse_event("research_presentation", research_run_event(run))

        reply_parts: list[str] = []
        stream = service.stream_async(prepared)
        buffered_validation = answer_validation_active(prepared)
        cancel_poll = (
            _make_cancel_poll(
                service,
                prepared.turn.id,
                prepared.turn.operation_id or "",
            )
            if prepared.turn.operation_id
            else None
        )

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
            # RQ1-C answer batch: research-backed turns buffer the whole
            # candidate until the publication gate passes; nothing is flushed
            # before complete_turn returns the verified text.  Binding failure
            # therefore emits zero candidate tokens.  The predicate is the
            # same one the gate itself uses, so policy-denied turns stream
            # token-by-token like ordinary chat.
            web_tools = prepared.rag.get("web_tools")
            if (
                isinstance(web_tools, dict)
                and web_tools.get("error")
                and web_tools.get("used") is not True
            ):
                notice = _web_failure_notice(web_tools)
                # For a research-validation turn, this route-owned UI notice is
                # not part of the model candidate and must not enter the binder
                # or its answer hash.  The underlying web-tools truth remains
                # available in route/RAG metadata.  Ordinary chat keeps the
                # historical learner-facing notice behavior.
                if not buffered_validation:
                    reply_parts.append(notice)
                    yield sse_event("token", {"text": notice})
            elif isinstance(web_tools, dict) and web_tools.get("used") is True:
                preview = _web_source_preview(web_tools)
                if preview and not buffered_validation:
                    reply_parts.append(preview)
                    yield sse_event("token", {"text": preview})
            async for token in _tokens_until_disconnected(
                stream,
                http_request,
                cancel_poll=cancel_poll,
            ):
                reply_parts.append(token)
                if not buffered_validation:
                    yield sse_event("token", {"text": token})

            # A provider stream may end without yielding when cancellation won
            # the generation-start CAS. Durable cancellation outranks the
            # transient transport signal so its terminal state can always be
            # settled through finish_cancelled_turn rather than a fenced
            # interrupt write.
            if cancel_poll is not None and cancel_poll():
                raise _TurnCancelled(
                    cancel_poll.turn_id,
                    cancel_poll.operation_id,
                )
            if await http_request.is_disconnected():
                raise _ClientDisconnected

            suffix = "".join(reply_parts)

            def complete_if_active() -> Any:
                # Second linearization check in the worker immediately before
                # complete_turn begins. The application service performs the
                # final checkpoint again immediately before each physical
                # binder provider attempt.
                if cancel_poll is not None and cancel_poll():
                    raise _TurnCancelled(
                        cancel_poll.turn_id,
                        cancel_poll.operation_id,
                    )
                return service.complete_turn(prepared, suffix)

            try:
                completed = await asyncio.to_thread(complete_if_active)
            except TurnCancelled as exc:
                # Application-level binder checkpoints use TurnCancelled so the
                # signal cannot be mistaken for a provider failure/retry. Route
                # it back through the existing streaming cancellation state
                # machine, which owns durable terminal settlement below.
                raise _TurnCancelled(exc.turn_id, exc.operation_id) from None
            except ValueError:
                # A cancel request can arrive after the binder provider call
                # started but before its completion write. The repository then
                # rejects the completion write; preserve cancellation semantics
                # instead of surfacing a generic stream error.
                if cancel_poll is not None and cancel_poll():
                    raise _TurnCancelled(
                        cancel_poll.turn_id,
                        cancel_poll.operation_id,
                    ) from None
                raise
            if buffered_validation:
                yield sse_event("token", {"text": completed.assistant_message})
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
                service.interrupt_turn(
                    prepared,
                    _publishable_partial(reply_parts, buffered_validation),
                )
            return
        except _TurnCancelled as exc:
            partial = _publishable_partial(reply_parts, buffered_validation)
            with suppress(ValueError):
                service.finish_cancelled_turn(prepared, partial)
            yield sse_event(
                "cancelled",
                {
                    "turn_id": exc.turn_id,
                    "operation_id": exc.operation_id,
                    "stage": "generation",
                    "partial": partial,
                },
            )
            return
        except asyncio.CancelledError:
            with suppress(ValueError):
                service.interrupt_turn(
                    prepared,
                    _publishable_partial(reply_parts, buffered_validation),
                )
            raise
        except Exception as exc:
            partial = _publishable_partial(reply_parts, buffered_validation)
            with suppress(ValueError):
                if partial:
                    service.interrupt_turn(prepared, partial)
                else:
                    service.fail_turn(prepared)
            yield sse_event(
                "error",
                {"message": str(exc), "error_type": type(exc).__name__},
            )
        finally:
            with suppress(RuntimeError):
                await stream.aclose()
            current = service.repository.get_chat_turn(prepared.turn.id)
            if current is not None and current.status == "streaming":
                partial = _publishable_partial(reply_parts, buffered_validation)
                with suppress(ValueError):
                    if partial:
                        service.interrupt_turn(prepared, partial)
                    else:
                        service.fail_turn(prepared)
            # G12 decision 15: run a queued archive once the operation settled.
            _drain_queued_archive(session_service, prepared.thread.id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _research_progress(run: Any) -> dict[str, Any]:
    deep = {}
    active_metrics = {}
    active_brief = {}
    context = getattr(run, "research_context", None)
    if isinstance(context, dict):
        candidate = context.get("deep")
        if isinstance(candidate, dict):
            deep = candidate
        candidate = context.get("claim_engine_metrics")
        if isinstance(candidate, dict):
            active_metrics = candidate
        candidate = context.get("claim_engine_evidence_brief")
        if isinstance(candidate, dict):
            active_brief = candidate

    def count(name: str) -> int | None:
        value = active_metrics.get(name)
        return value if type(value) is int and value >= 0 else None

    steps = [
        step for step in deep.get("steps", []) if isinstance(step, dict)
    ]
    notes = [note for note in deep.get("notes", []) if isinstance(note, dict)]
    last_step = steps[-1] if steps else None
    return {
        "run_id": run.id,
        "status": run.status,
        "stage": run.stage,
        "provider_status": run.provider_status,
        "stop_reason": run.stop_reason,
        "error": run.error,
        "query_attempt_count": len(run.query_attempts),
        "selected_source_count": len(run.selected_sources),
        "candidate_count": count("candidate_count"),
        "read_count": count("read_count"),
        "cluster_count": count("cluster_count"),
        "open_critical_gap_count": count("open_critical_gap_count"),
        "active_phase": str(active_metrics.get("phase") or "") or None,
        "gate_status": str(active_brief.get("gate_status") or "") or None,
        "version": run.version,
        # G18 deep-research journey fields.
        "round": int(deep.get("round_index") or 0) or None,
        "notes_count": len(notes),
        "last_step_kind": (last_step or {}).get("kind"),
        "last_step_text": (last_step or {}).get("text"),
    }


def _web_failure_notice(web_tools: dict[str, Any]) -> str:
    if web_tools.get("evidence_status") != "candidate_only":
        return "联网搜索失败，本回答未使用联网来源。\n\n"
    attempted_read = any(
        isinstance(call, dict) and call.get("name") == "web_read"
        for key in ("calls", "diagnostic_calls")
        for call in (web_tools.get(key) or [])
    )
    if attempted_read:
        return (
            "联网搜索获得了候选链接，已尝试读取，但未获得可用于回答的相关正文；"
            "本回答不将这些候选作为结论来源。\n\n"
        )
    return (
        "联网搜索获得了候选链接，但尚未读取正文；"
        "本回答不将这些候选作为结论来源。\n\n"
    )


def _web_source_preview(web_tools: dict[str, Any]) -> str:
    """Render only sources whose page/API payload entered answer context."""

    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    used_sources = web_tools.get("used_sources")
    if not isinstance(used_sources, list):
        return ""
    for item in used_sources:
        if not isinstance(item, dict):
            continue
        title = " ".join(str(item.get("title") or "").split())
        url = str(item.get("url") or "").strip()
        if not title or not url.startswith(("https://", "http://")):
            continue
        key = url.rstrip("/").casefold()
        if key in seen:
            continue
        seen.add(key)
        sources.append((title, url))
    if not sources:
        return ""
    total = len(sources)
    preview = sources[:3]
    lines = [f"联网正文读取已完成，本次使用的来源（预览 {len(preview)}/{total}）："]
    lines.extend(f"- [{title}]({url})" for title, url in preview)
    return "\n".join(lines) + "\n\n"


def _publishable_partial(
    reply_parts: list[str], buffered_validation: bool
) -> str:
    """Return only text that was already eligible for learner publication."""

    if buffered_validation:
        return ""
    return "".join(reply_parts)


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
    cancel_poll: Any = None,
) -> AsyncIterator[str]:
    """Wait for provider tokens while keeping client disconnects and cancellation observable."""

    while True:
        next_token: asyncio.Task[str] = asyncio.create_task(
            _next_stream_token(stream)
        )
        try:
            while not next_token.done():
                done, _ = await asyncio.wait({next_token}, timeout=poll_interval)
                if done:
                    break
                if cancel_poll is not None and cancel_poll():
                    next_token.cancel()
                    with suppress(asyncio.CancelledError):
                        await next_token
                    raise _TurnCancelled(cancel_poll.turn_id, cancel_poll.operation_id)
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


def _make_cancel_poll(
    service: ChatService, turn_id: str, operation_id: str
) -> Any:
    """Build a cooperative cancel poll callable for the streaming loop."""

    def poll() -> bool:
        return service.repository.turn_cancel_requested(turn_id, operation_id)

    poll.turn_id = turn_id  # type: ignore[attr-defined]
    poll.operation_id = operation_id  # type: ignore[attr-defined]
    return poll


async def _next_stream_token(stream: AsyncIterator[str]) -> str:
    return await anext(stream)


@router.post("/chat/turns/{turn_id}/cancel", response_model=CancelTurnResponse)
def cancel_turn_endpoint(
    turn_id: str,
    request: CancelTurnRequest,
    service: ChatServiceDependency,
) -> CancelTurnResponse:
    """Register a cooperative cancellation request for an active turn.

    G12 decision 20: the POST only confirms the request was registered; the
    client polls the turn-status endpoint for the durable terminal state.
    Pre-reservation cancellations (turn row not yet persisted) wait briefly
    for the row to appear, mirroring the WebLookup ``cancel_owned_by_turn``
    bounded-wait precedent.
    """
    import time

    deadline = time.monotonic() + 2.0
    outcome = "not_found"
    turn = None
    while True:
        outcome, turn = service.repository.request_turn_cancel(
            turn_id,
            expected_operation_id=request.expected_operation_id,
            reason=request.reason,
        )
        if outcome != "not_found" or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Chat turn not found")
    if outcome == "operation_mismatch":
        raise HTTPException(status_code=409, detail="Chat turn operation mismatch")
    status = turn.status if turn is not None else None
    cancel_at = turn.cancel_requested_at if turn is not None else None
    return CancelTurnResponse(
        turn_id=turn_id,
        outcome=outcome,
        status=status,
        cancel_requested_at=cancel_at,
    )


@router.get("/chat/turns/{turn_id}/status", response_model=TurnStatusResponse)
def turn_status_endpoint(
    turn_id: str,
    service: ChatServiceDependency,
    session_service: SessionServiceDependency,
) -> TurnStatusResponse:
    """Poll the durable terminal state of a turn (G12 decision 20)."""
    turn = service.repository.get_chat_turn(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Chat turn not found")
    # G12 decision 15: the status poll doubles as a queue drain trigger, so a
    # persisted archive intent executes even without a live stream finally.
    _drain_queued_archive(session_service, turn.thread_id)
    return TurnStatusResponse(
        turn_id=turn_id,
        status=turn.status,
        operation_id=turn.operation_id,
        cancel_requested_at=turn.cancel_requested_at,
        cancel_stage=turn.cancel_stage,
        cancel_reason=turn.cancel_reason,
        assistant_message=turn.assistant_message,
    )


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
    research_sources: dict[str, Any] | None = None
    answer_validation: dict[str, Any] | None = None
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
        research_sources = research_sources_snapshot(run)
        # The validation plan is constructed only from the server-resolved
        # ResearchRun object.  Provenance requires the claim-engine runtime
        # traces on that object; rows may legitimately be empty (old or
        # gated-out runs), in which case the gate fails closed instead of
        # treating the turn as non-research.
        if research_run_provenance(run):
            answer_validation = {
                "evidence_rows": research_binding_rows(run),
                "allowed_attempts": 1,
            }
    return PolicyChatCommand(
        user_input=request.user_input,
        review_prompt_turn_id=request.review_prompt_turn_id,
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
        research_sources=research_sources,
        answer_validation=answer_validation,
        continuation_of_turn_id=request.continuation_of_turn_id,
        retry_of_turn_id=request.retry_of_turn_id,
        partial_reply=request.partial_reply,
        turn_id=request.turn_id,
        operation_id=request.operation_id,
    )
