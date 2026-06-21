from __future__ import annotations

import asyncio
import time
from dataclasses import replace

import pytest

from src.api.models.wechat import WechatMessageRequest
from src.api.routes.wechat_routes import send_wechat_message_stream


class DisconnectRequest:
    async def is_disconnected(self) -> bool:
        return True


def _blocking_stream(*args, **kwargs):
    should_cancel = kwargs["should_cancel"]

    def tokens():
        while not should_cancel():
            time.sleep(0.005)
        return
        yield "unreachable"

    return tokens(), False


def _partial_stream(*args, **kwargs):
    should_cancel = kwargs["should_cancel"]

    def tokens():
        yield "partial"
        while not should_cancel():
            time.sleep(0.005)

    return tokens(), False


async def _consume(service, request) -> str:
    response = await send_wechat_message_stream(
        WechatMessageRequest(message="question", selected_model="flash"),
        request,
        service,
    )
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


@pytest.mark.parametrize(
    ("stream_factory", "expected_partial"),
    [(_blocking_stream, ""), (_partial_stream, "partial")],
)
def test_disconnect_settles_exchange_and_releases_lease(
    runtime_test_context, stream_factory, expected_partial
):
    service = runtime_test_context.group_service
    service.dependencies = replace(
        service.dependencies, generate_reply_stream=stream_factory
    )

    body = asyncio.run(
        asyncio.wait_for(_consume(service, DisconnectRequest()), timeout=2)
    )

    thread = runtime_test_context.group_repository.list_threads()[0]
    messages = runtime_test_context.group_repository.list_messages(thread.id)
    assert "event: done" not in body
    assert [message.status for message in messages] == ["interrupted", "interrupted"]
    assert messages[-1].content == expected_partial
    assert runtime_test_context.group_repository.get_thread(thread.id).active_operation_id is None


def test_asgi_cancellation_settles_exchange_and_releases_lease(runtime_test_context):
    service = runtime_test_context.group_service
    service.dependencies = replace(
        service.dependencies, generate_reply_stream=_blocking_stream
    )

    async def scenario():
        response = await send_wechat_message_stream(
            WechatMessageRequest(message="cancelled", selected_model="flash"),
            DisconnectRequest(),
            service,
        )
        iterator = response.body_iterator
        await anext(iterator)
        await anext(iterator)
        pending = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0.02)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(asyncio.wait_for(scenario(), timeout=2))
    thread = runtime_test_context.group_repository.list_threads()[0]
    messages = runtime_test_context.group_repository.list_messages(thread.id)
    assert [message.status for message in messages] == ["interrupted", "interrupted"]
    assert runtime_test_context.group_repository.get_thread(thread.id).active_operation_id is None
