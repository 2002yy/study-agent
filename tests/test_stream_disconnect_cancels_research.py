"""A client disconnect during preparation must cancel the research run.

The acceptance harness times out after 300 s; a test timeout must also stop the
backend's later paid work, not merely stop waiting for the SSE body.  These
tests pin that behaviour (and the exact boundary) with the real endpoint.
"""

from __future__ import annotations

import asyncio
import time

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import chat_stream_endpoint
from src.application.chat_service import ChatDependencies, ChatService
from src.context_builder import build_messages
from src.mode_manager import RuntimeModes
from src.performance_budget import chat_max_tokens
from src.router import route_request
from src.tools.web_agent import WebToolTrace


class FakeRagResult:
    context = ""

    def to_dict(self):
        return {"status": "skipped", "context": "", "result_count": 0}


class DisconnectRequest:
    async def is_disconnected(self) -> bool:
        return True


class ConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


def _service(runtime_test_context) -> ChatService:
    def slow_resolve(*_args, **_kwargs):
        # Preparation outlives several 50 ms disconnect polls.
        time.sleep(0.4)
        return WebToolTrace(enabled=False)

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
            async_stream_chat=lambda *args, **kwargs: _empty(),
            chat_max_tokens=chat_max_tokens,
            resolve_web_tools=slow_resolve,
        )
    )


async def _empty():
    if False:  # pragma: no cover - an empty async generator
        yield ""


class CancelRecordingResearchService:
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, float]] = []

    def cancel_owned_by_turn(self, turn_id: str, *, wait_seconds: float = 0.0):
        self.cancelled.append((turn_id, wait_seconds))
        return None

    def latest_owned_by_turn(self, turn_id: str):
        return None


async def _consume(service, research_service, request, session_id, turn_id):
    response = await chat_stream_endpoint(
        ChatRequest(user_input="question", session_id=session_id, turn_id=turn_id),
        request,
        service,
        research_service,
        None,
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def test_disconnect_during_preparation_cancels_the_owned_research_run(runtime_test_context):
    research = CancelRecordingResearchService()
    service = _service(runtime_test_context)

    body = asyncio.run(
        _consume(service, research, DisconnectRequest(), "dc-session", "turn-dc-1")
    )

    # The run behind this turn is cancelled *before* waiting for preparation.
    assert research.cancelled and research.cancelled[0][0] == "turn-dc-1"
    assert "event: done" not in body


def test_connected_client_never_triggers_the_cancel_path(runtime_test_context):
    research = CancelRecordingResearchService()
    service = _service(runtime_test_context)

    asyncio.run(_consume(service, research, ConnectedRequest(), "keep-session", "turn-keep-1"))

    assert research.cancelled == []
