from __future__ import annotations

import asyncio
import time

from src.tools.web_agent import WebToolTrace

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import (
    _web_failure_notice,
    _web_source_preview,
    chat_stream_endpoint,
)
from src.application.chat_service import ChatDependencies, ChatService
from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.performance_budget import chat_max_tokens
from src.router import route_request


class FakeRagResult:
    context = ""

    def to_dict(self):
        return {"status": "skipped", "context": "", "result_count": 0}


def test_rejected_or_failed_read_is_not_reported_as_never_attempted():
    notice = _web_failure_notice({
        "evidence_status": "candidate_only",
        "calls": [{"name": "web_search"}],
        "diagnostic_calls": [{"name": "web_read", "ok": False}],
    })
    assert "已尝试读取" in notice
    assert "尚未读取正文" not in notice


class DisconnectRequest:
    def __init__(self):
        self.checked = asyncio.Event()

    async def is_disconnected(self) -> bool:
        self.checked.set()
        return True


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def _service(runtime_test_context, async_stream_chat) -> ChatService:
    return runtime_test_context.override_chat(
        ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
            route_request=route_request,
            retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
            build_messages=build_messages,
            chat=lambda *args, **kwargs: "unused",
            stream_chat=lambda *args, **kwargs: iter(()),
            async_stream_chat=async_stream_chat,
            chat_max_tokens=chat_max_tokens,
        )
    )


async def _consume_stream(
    service,
    research_service,
    request,
    session_id: str,
    *,
    turn_id: str | None = None,
    session_service=None,
) -> str:
    response = await chat_stream_endpoint(
        ChatRequest(user_input="question", session_id=session_id, turn_id=turn_id),
        request,
        service,
        research_service,
        session_service,
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def test_preparation_streams_owned_research_progress_before_session(
    runtime_test_context,
):
    async def tokens(*args, **kwargs):
        yield "done"

    service = _service(runtime_test_context, tokens)
    original_start_turn = service.start_turn

    def delayed_start_turn(command):
        run = runtime_test_context.web_lookup_service.create(
            command.user_input,
            owner_thread_id=command.thread_id,
            owner_turn_id=command.turn_id,
            run_kind="chat_tool_loop",
        )
        operation_id = runtime_test_context.web_lookup_service.begin_tool_trace(run.id)
        time.sleep(0.12)
        runtime_test_context.web_lookup_service.record_tool_trace(
            run.id,
            calls=[],
            source_block="",
            operation_id=operation_id,
        )
        return original_start_turn(command)

    service.start_turn = delayed_start_turn

    body = asyncio.run(
        _consume_stream(
            service,
            runtime_test_context.web_lookup_service,
            ConnectedRequest(),
            "research-progress-session",
            turn_id="research-progress-turn",
                session_service=runtime_test_context.session_service,
        )
    )

    assert "event: research" in body
    assert '"stage": "searching"' in body
    assert body.index("event: research") < body.index("event: session")


def test_failed_research_emits_visible_notice_before_model_tokens(runtime_test_context):
    async def tokens(*args, **kwargs):
        yield "offline answer"

    service = _service(runtime_test_context, tokens)
    dependencies = service.dependencies
    service.dependencies = ChatDependencies(
        **{
            **dependencies.__dict__,
            "resolve_web_tools": lambda *_args, **_kwargs: WebToolTrace(
                error="TimeoutError: provider timeout",
                run_id="web_lookup_failed",
            ),
        }
    )

    body = asyncio.run(
        _consume_stream(
            service,
            runtime_test_context.web_lookup_service,
            ConnectedRequest(),
            "failed-research-visible-notice",
                session_service=runtime_test_context.session_service,
        )
    )

    notice = "联网搜索失败，本回答未使用联网来源。"
    assert notice in body
    assert body.index(notice) < body.index("offline answer")


def test_source_preview_is_labeled_as_three_of_total_used_sources():
    preview = _web_source_preview(
        {
            "used_sources": [
                {
                    "title": f"Read source {index}",
                    "url": f"https://example.test/{index}",
                }
                for index in range(1, 6)
            ]
        }
    )

    assert "本次使用的来源（预览 3/5）" in preview
    assert "Read source 1" in preview
    assert "Read source 3" in preview
    assert "Read source 4" not in preview


def test_candidate_only_search_emits_truthful_notice_before_model_tokens(
    runtime_test_context,
):
    async def tokens(*args, **kwargs):
        yield "bounded answer"

    service = _service(runtime_test_context, tokens)
    dependencies = service.dependencies
    service.dependencies = ChatDependencies(
        **{
            **dependencies.__dict__,
            "resolve_web_tools": lambda *_args, **_kwargs: WebToolTrace(
                calls=(
                    {
                        "name": "web_search",
                        "arguments": {"query": "candidate"},
                        "result": {
                            "status": "ok",
                            "results": [
                                {
                                    "title": "Candidate",
                                    "url": "https://example.test/candidate",
                                }
                            ],
                        },
                    },
                )
            ),
        }
    )

    body = asyncio.run(
        _consume_stream(
            service,
            runtime_test_context.web_lookup_service,
            ConnectedRequest(),
            "candidate-only-visible-notice",
            session_service=runtime_test_context.session_service,
        )
    )

    notice = "候选链接，但尚未读取正文"
    assert notice in body
    assert body.index(notice) < body.index("bounded answer")


def test_successful_research_emits_source_preview_before_model_tokens(
    runtime_test_context,
):
    async def tokens(*args, **kwargs):
        yield "synthesized answer"

    service = _service(runtime_test_context, tokens)
    dependencies = service.dependencies
    service.dependencies = ChatDependencies(
        **{
            **dependencies.__dict__,
            "resolve_web_tools": lambda *_args, **_kwargs: WebToolTrace(
                calls=(
                    {
                        "name": "web_search",
                        "arguments": {"query": "official docs"},
                        "result": {
                            "status": "ok",
                            "results": [
                                {
                                    "title": "Official documentation",
                                    "url": "https://example.test/docs",
                                }
                            ],
                        },
                    },
                    {
                        "name": "web_read",
                        "arguments": {"url": "https://example.test/docs"},
                        "result": {
                            "ok": True,
                            "url": "https://example.test/docs",
                            "content": "Official documentation body",
                        },
                    },
                ),
                run_id="web_lookup_found",
            ),
        }
    )

    body = asyncio.run(
        _consume_stream(
            service,
            runtime_test_context.web_lookup_service,
            ConnectedRequest(),
            "successful-research-visible-preview",
                session_service=runtime_test_context.session_service,
        )
    )

    assert "联网正文读取已完成" in body
    assert "本次使用的来源（预览 1/1）" in body
    assert "https://example.test/docs" in body
    assert body.index("联网正文读取已完成") < body.index("synthesized answer")


def test_disconnect_before_first_token_interrupts_turn(runtime_test_context):
    cancelled = asyncio.Event()

    async def blocked_stream(*args, **kwargs):
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            cancelled.set()

    async def scenario():
        service = _service(runtime_test_context, blocked_stream)
        body = await asyncio.wait_for(
            _consume_stream(
                service,
                runtime_test_context.web_lookup_service,
                DisconnectRequest(),
                "disconnect-before-token",
                session_service=runtime_test_context.session_service,
            ),
            timeout=1,
        )
        assert cancelled.is_set()
        return body

    body = asyncio.run(scenario())
    turns = runtime_test_context.repository.list_chat_turns("disconnect-before-token")

    assert "event: done" not in body
    assert len(turns) == 1
    assert turns[0].status == "interrupted"
    assert turns[0].assistant_message == ""


def test_disconnect_after_partial_token_preserves_full_partial(runtime_test_context):
    cancelled = asyncio.Event()

    async def partial_then_block(*args, **kwargs):
        try:
            yield "partial"
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def scenario():
        service = _service(runtime_test_context, partial_then_block)
        body = await asyncio.wait_for(
            _consume_stream(
                service,
                runtime_test_context.web_lookup_service,
                DisconnectRequest(),
                "disconnect-after-token",
                session_service=runtime_test_context.session_service,
            ),
            timeout=1,
        )
        assert cancelled.is_set()
        return body

    body = asyncio.run(scenario())
    turns = runtime_test_context.repository.list_chat_turns("disconnect-after-token")

    assert 'data: {"text": "partial"}' in body
    assert "event: done" not in body
    assert len(turns) == 1
    assert turns[0].status == "interrupted"
    assert turns[0].assistant_message == "partial"
