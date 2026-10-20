"""Explicit opt-in/auth and HTTP lifecycle over owned fake DeepSeek runs."""

import asyncio
import json

from fastapi import FastAPI
import httpx
import pytest
from starlette.requests import ClientDisconnect

from src.api.routes.conversation_events_routes import create_conversation_events_router
from src.application.conversation_bounded_loop import LoopStopped
from src.application.conversation_loop_session import ConversationLoopSession
from tests.test_conversation_owned_binding import setup


TOKEN = {"authorization": "Bearer fake-api-token"}
URL = "/chat/threads/chat-1/turns/turn-2/agent-events"
BODY = {"operation_id": "operation-1"}


def app_setup(tmp_path, *, enabled=True, starter=None):
    binding, repo, path, clients, requests, admitted, thread, turn = setup(tmp_path)
    closed, authorized = [], []

    async def authorize(request, thread_id, turn_id, operation_id):
        authorized.append((thread_id, turn_id, operation_id))
        return request.headers.get("authorization") == TOKEN["authorization"]

    async def on_closed(thread_id, turn_id, operation_id, receipt):
        closed.append((thread_id, turn_id, operation_id, receipt))

    args = {
        "start_run": starter or binding.start,
        "authorize": authorize,
        "on_closed": on_closed,
    }
    if enabled:
        args["enabled"] = lambda: True
    app = FastAPI()
    app.include_router(create_conversation_events_router(**args))
    return app, clients, requests, admitted, closed, authorized, repo


def test_owned_provisional_sse_and_close_callback(tmp_path):
    async def run():
        app, clients, requests, _, closed, authorized, repo = app_setup(tmp_path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(URL, json=BODY, headers=TOKEN)
        assert result.status_code == 200
        assert result.headers["content-type"].startswith("text/event-stream")
        assert result.headers["cache-control"] == "no-store"
        frames = [
            json.loads(line[6:])
            for line in result.text.splitlines()
            if line.startswith("data: ")
        ]
        assert any(frame["kind"] == "answer" for frame in frames)
        assert frames[-1]["kind"] == "terminal" and frames[-1]["status"] == "answered"
        assert all(frame["publication_status"] == "provisional" for frame in frames)
        assert clients[0].is_closed() and len(requests) == 2
        assert authorized == [("chat-1", "turn-2", "operation-1")]
        assert len(closed) == 1 and closed[0][:3] == authorized[0]
        assert closed[0][3].status == "stopped"
        assert repo.get_chat_turn("turn-2").assistant_message == ""

    asyncio.run(run())


@pytest.mark.parametrize(
    "case,expected",
    [("disabled", 404), ("unauthorized", 403), ("foreign", 409), ("replay", 409)],
)
def test_denied_requests_never_admit_or_open_sdk(tmp_path, case, expected):
    async def run():
        app, clients, requests, admitted, closed, _, _ = app_setup(
            tmp_path, enabled=case != "disabled"
        )
        headers = {} if case == "unauthorized" else dict(TOKEN)
        if case == "replay":
            headers["last-event-id"] = "display-only-id"
        url = URL.replace("chat-1", "foreign") if case == "foreign" else URL
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(url, json=BODY, headers=headers)
        assert result.status_code == expected
        assert not clients and not requests and not admitted and not closed

    asyncio.run(run())


@pytest.mark.parametrize(
    "extra",
    [
        "chat_history",
        "user_message",
        "model_budget",
        "available_tools",
        "evidence_summary",
    ],
)
def test_client_owned_context_tools_and_budgets_are_rejected(tmp_path, extra):
    async def run():
        app, clients, requests, admitted, _, _, _ = app_setup(tmp_path)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                URL, json={**BODY, extra: "must-not-use"}, headers=TOKEN
            )
        assert (
            result.status_code == 422 and not clients and not requests and not admitted
        )

    asyncio.run(run())


def scope():
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": URL,
        "raw_path": URL.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"authorization", b"Bearer fake-api-token"),
        ],
        "client": ("test", 1),
        "server": ("test", 80),
    }


@pytest.mark.parametrize("when", ["headers", "first_body"])
def test_send_disconnect_closes_even_before_body_is_read(tmp_path, when):
    async def run():
        app, clients, requests, _, closed, _, _ = app_setup(tmp_path)
        first = [True]

        async def receive():
            if first[0]:
                first[0] = False
                return {
                    "type": "http.request",
                    "body": json.dumps(BODY).encode(),
                    "more_body": False,
                }
            await asyncio.Event().wait()

        async def send(event):
            if (when == "headers" and event["type"] == "http.response.start") or (
                when == "first_body" and event["type"] == "http.response.body"
            ):
                raise OSError("client disconnected")

        with pytest.raises(ClientDisconnect):
            await app(scope(), receive, send)
        assert len(closed) == 1 and closed[0][3].status == "closed"
        if when == "headers":
            assert not clients and not requests
        else:
            assert clients[0].is_closed() and len(requests) == 1

    asyncio.run(run())


def test_asgi_disconnect_cancels_active_run_and_notifies_once(tmp_path):
    async def run():
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def source():
            try:
                entered.set()
                await asyncio.Event().wait()
                yield LoopStopped("unreachable", 0, 0)
            finally:
                stopped.set()

        def start(*args):
            return ConversationLoopSession("owned-request", source())

        app, _, _, _, closed, _, _ = app_setup(tmp_path, starter=start)
        first = [True]

        async def receive():
            if first[0]:
                first[0] = False
                return {
                    "type": "http.request",
                    "body": json.dumps(BODY).encode(),
                    "more_body": False,
                }
            await entered.wait()
            return {"type": "http.disconnect"}

        async def send(event):
            pass

        target = scope()
        target["asgi"]["spec_version"] = "2.0"
        await app(target, receive, send)
        assert stopped.is_set() and len(closed) == 1
        assert closed[0][3].status == "cancelled" and closed[0][3].outcome_unknown

    asyncio.run(run())


def test_private_admission_error_is_not_exposed(tmp_path):
    async def run():
        def bad_start(*args):
            raise RuntimeError("private-host-budget-details")

        app, clients, _, _, closed, _, _ = app_setup(tmp_path, starter=bad_start)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(URL, json=BODY, headers=TOKEN)
        assert result.status_code == 503
        assert (
            "private-host-budget-details" not in result.text
            and not clients
            and not closed
        )

    asyncio.run(run())
