"""CL-M3 QD-3c: the routes are readers, and a reader cannot end a research.

The contract's R-3 is the reason this file exists: "a research is not lost because
the user switched chat, refreshed the page, or lost an ordinary SSE connection.
Only an explicit user cancellation or a policy termination may end it."

There are two ways to break that, and this file closes both.

- **A route that cancels.** If the disconnect path of the event stream called
  anything that ended a research, then closing a browser tab would end the
  research. The tests here disconnect and then assert that the research is still
  there, still resumable, and still able to advance.

- **A route that leaks another thread's research.** If the thread view were not
  scoped, then opening one chat would show - and could act on - another chat's
  research. The scoping tests assert that a thread's view contains nothing but its
  own researches.

The route module is also checked for the *absence* of a cancel call. A test that
reads the source and refuses any ``cancel`` in it is a guard that cannot be
bypassed by a future edit that adds one - the same reasoning as the subscription
type carrying no cancel method.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.research_routes import router
from src.application.research_feed import ResearchFeed
from src.domain.research_state import STATE_CHECKPOINTED, ResearchRound
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository

RESEARCH = "research-1"
THREAD = "thread-1"
OTHER_THREAD = "thread-2"

SOURCE = Path(__file__).resolve().parents[1] / "src" / "api" / "routes" / "research_routes.py"


@pytest.fixture
def repository(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    return ResearchStateRepository(database)


@pytest.fixture
def feed(repository):
    return ResearchFeed(repository)


@pytest.fixture
def app(feed):
    application = FastAPI()
    application.include_router(router)

    def _feed_override():
        return feed

    application.dependency_overrides[
        __import__("src.api.routes.research_routes", fromlist=["get_research_feed"]).get_research_feed
    ] = _feed_override
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


def _create(repository, research_id=RESEARCH, *, thread_id=THREAD):
    return repository.create(
        research_id=research_id,
        thread_id=thread_id,
        operation_id=f"operation-{research_id}",
        original_question="what is X?",
        question="what is X?",
        tier="standard",
    )


def _advance_one_round(repository, research_id=RESEARCH):
    claimed = repository.claim(research_id, owner="worker-1")
    state = repository.checkpoint(
        research_id,
        ResearchRound(
            research_id=research_id,
            round_index=0,
            question="what is X?",
            queries=("query-0",),
            evidence=("fact-0",),
        ),
        owner="worker-1",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )
    repository.release(
        research_id, owner="worker-1", fencing_token=claimed.fencing_token
    )
    return state


async def _drain_until(app, path, *, until, limit=400):
    """Drive the streaming endpoint over raw ASGI, then disconnect it.

    The test client cannot be used for this: closing a streamed response does
    not deliver ``http.disconnect`` to the application, so the endpoint's
    disconnect branch is never reached and the generator waits forever. Driving
    ASGI directly is the only way to say "the client went away" and to observe
    what the endpoint does about it.

    The read is bounded by ``limit`` polls so that a broken endpoint fails the
    test instead of hanging it.
    """

    messages: list[dict] = []
    disconnected = asyncio.Event()

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    # The scope must carry the path in both forms: Starlette routes on
    # ``raw_path`` and reads the query from ``query_string``. A scope with the
    # right ``path`` but a placeholder ``raw_path`` answers 404, which looks
    # exactly like an endpoint that never produces a frame.
    raw_path, _, query = path.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "path": raw_path,
        "raw_path": raw_path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(b"host", b"test")],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
    }

    task = asyncio.create_task(app(scope, receive, send))
    try:
        for _ in range(limit):
            if until(messages):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the stream never produced the expected frame")
        disconnected.set()
        # The endpoint must finish on its own once the client is gone. If it does
        # not, the disconnect branch is missing and the generator leaks.
        await asyncio.wait_for(task, timeout=5)
    finally:
        disconnected.set()
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
    return messages


def _body_text(messages) -> str:
    return "".join(
        message.get("body", b"").decode("utf-8")
        for message in messages
        if message.get("type") == "http.response.body"
    )


# --- the thread view -----------------------------------------------------------------


def test_a_thread_view_lists_that_threads_researches(client, repository):
    _create(repository, RESEARCH, thread_id=THREAD)
    _create(repository, "research-2", thread_id=OTHER_THREAD)

    response = client.get(f"/sessions/{THREAD}/research")

    assert response.status_code == 200
    data = response.json()
    assert [item["research_id"] for item in data["researches"]] == [RESEARCH]


def test_a_thread_view_carries_the_finished_rounds(client, repository):
    _create(repository)
    _advance_one_round(repository)

    response = client.get(f"/sessions/{THREAD}/research")

    data = response.json()
    assert data["researches"][0]["round_index"] == 1
    assert data["researches"][0]["rounds"][0]["evidence"] == ["fact-0"]
    assert data["researches"][0]["status"] == STATE_CHECKPOINTED


def test_a_thread_view_of_an_unknown_thread_is_empty_not_an_error(client):
    response = client.get("/sessions/no-such-thread/research")

    assert response.status_code == 200
    assert response.json()["researches"] == []


def test_one_research_is_readable_on_its_own(client, repository):
    _create(repository)
    _advance_one_round(repository)

    response = client.get(f"/research/{RESEARCH}")

    assert response.status_code == 200
    data = response.json()
    assert data["research_id"] == RESEARCH
    assert data["round_index"] == 1


def test_an_unknown_research_is_a_404(client):
    response = client.get("/research/no-such-research")

    assert response.status_code == 404


def test_the_snapshot_reports_what_a_client_missed(client, repository):
    _create(repository)
    _advance_one_round(repository)

    response = client.get(f"/research/{RESEARCH}?after_event_seq=0")

    data = response.json()
    assert data["missed_events"] == 1
    assert len(data["events"]) == 1


# --- the disconnect guard ------------------------------------------------------------


def test_the_route_module_contains_no_cancel_call():
    """A guard that cannot be bypassed.

    The disconnect path of an SSE endpoint is exactly where a cancel call would
    creep in, and once it is there it looks harmless. Reading the source and
    refusing any cancel in it means a future edit that adds one fails here rather
    than silently ending researches when a browser tab closes.
    """

    source = SOURCE.read_text(encoding="utf-8")

    offenders = re.findall(r"\bcancel\w*\s*\(", source)
    assert offenders == [], f"the research routes must not call {offenders}"


def test_the_route_module_does_not_interrupt_a_turn_either():
    source = SOURCE.read_text(encoding="utf-8")

    assert "interrupt_turn" not in source
    assert "cancel_owned_by_turn" not in source


def test_a_disconnected_client_does_not_end_the_research(app, repository, feed):
    """The core of R-3, at the route level.

    The client opens the event stream and goes away. The research must still be
    there, still be resumable, and still be advanceable by a worker.
    """

    _create(repository)
    _advance_one_round(repository)
    registry = feed.registry

    asyncio.run(
        _drain_until(
            app,
            f"/sessions/{THREAD}/research/events",
            until=lambda messages: "round_completed" in _body_text(messages),
        )
    )

    state = repository.load(RESEARCH)
    assert state is not None
    assert state.status == STATE_CHECKPOINTED
    assert state.terminal is False
    # The watcher is gone; the research is not.
    assert registry.watchers_of_thread(THREAD) == 0


def test_a_research_survives_a_client_that_leaves_and_comes_back(client, repository):
    """The reconnect path: the research kept its rounds, and the client sees them."""

    _create(repository)
    _advance_one_round(repository)

    # A worker continues while nobody is watching.
    claimed = repository.claim(RESEARCH, owner="worker-2")
    repository.checkpoint(
        RESEARCH,
        ResearchRound(
            research_id=RESEARCH,
            round_index=1,
            question="what is X?",
            queries=("query-1",),
            evidence=("fact-1",),
        ),
        owner="worker-2",
        fencing_token=claimed.fencing_token,
        expected_state_version=claimed.state_version,
    )

    response = client.get(f"/research/{RESEARCH}")

    data = response.json()
    assert data["round_index"] == 2
    assert [record["round_index"] for record in data["rounds"]] == [0, 1]


def test_switching_thread_does_not_disturb_the_other_thread(app, repository, feed):
    """Two threads, two researches, one watcher leaving. Nothing else moves."""

    _create(repository, RESEARCH, thread_id=THREAD)
    _create(repository, "research-2", thread_id=OTHER_THREAD)
    _advance_one_round(repository, RESEARCH)
    _advance_one_round(repository, "research-2")

    asyncio.run(
        _drain_until(
            app,
            f"/sessions/{THREAD}/research/events",
            until=lambda messages: "round_completed" in _body_text(messages),
        )
    )

    other = repository.load("research-2")
    assert other is not None
    assert other.status == STATE_CHECKPOINTED
    assert other.round_index == 1
    assert other.terminal is False


def test_the_event_stream_sends_the_events_of_the_thread(app, repository):
    _create(repository)
    _advance_one_round(repository)

    messages = asyncio.run(
        _drain_until(
            app,
            f"/sessions/{THREAD}/research/events",
            until=lambda messages: "round_completed" in _body_text(messages),
        )
    )

    body = _body_text(messages)
    assert "id: " in body
    assert "event: round_completed" in body


def test_the_event_stream_resumes_from_a_cursor(app, repository):
    """Nothing new after the cursor, so no event frames - only heartbeats.

    The heartbeat matters here for a second reason: a reader that waits for the
    next line has to be able to get one even when the research is quiet, or it
    waits forever and cannot tell a quiet research from a dead connection.
    """

    _create(repository)
    _advance_one_round(repository)
    cursor = repository.events(RESEARCH)[0].event_seq

    messages = asyncio.run(
        _drain_until(
            app,
            f"/sessions/{THREAD}/research/events?after_event_seq={cursor}",
            until=lambda messages: "heartbeat" in _body_text(messages),
        )
    )

    body = _body_text(messages)
    assert "heartbeat" in body
    assert "round_completed" not in body
