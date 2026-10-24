"""CL-M3 QD-3c: read-only routes over persistent research.

Two endpoints, both of them readers:

- ``GET /sessions/{thread_id}/research`` - the researches of one thread, with their
  finished rounds and their current state.
- ``GET /sessions/{thread_id}/research/events`` - the same, plus the events a
  reconnecting client missed.

**Nothing here can end a research.** That is the point of the module. The contract's
R-3 says a research survives the user changing chat, refreshing the page or losing
an ordinary SSE connection; only an explicit cancellation or a policy termination
may end it. So the disconnect path of the SSE endpoint removes a subscription and
does nothing else. There is no cancel call in this file, and there is no branch that
could grow one by accident - the research's fate belongs to the executor and, later,
to the cancellation policy.

The endpoint is deliberately a *reader* rather than a participant in the research's
lifecycle. It polls the durable event log, which is the same shape the existing
research-progress SSE uses. A poller that loses its connection loses nothing, because
the log is in the database and the cursor is in the client's hand.

``Last-Event-ID`` is honoured here, with the sequence the research event log
allocates. This is a *separate* mechanism from the one in
``conversation_events_routes.py``, which deliberately rejects replay: that endpoint
serves a single-consumer in-process session whose receipts were never durable. Two
different subsystems, two different contracts, and neither is changed to suit the
other.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.application.research_feed import ResearchFeed
from src.application.runtime_repository import get_research_feed
from src.repositories.research_state_repository import ResearchNotFound

router = APIRouter(tags=["research"])
ResearchFeedDependency = Annotated[ResearchFeed, Depends(get_research_feed)]

# How often the SSE endpoint looks for new events. The same 50ms the existing
# research-progress stream uses: the research it serves is minutes long, so a
# tighter poll would burn CPU to deliver nothing sooner.
POLL_SECONDS = 0.05

# How often a quiet stream says "still here". Without it, a client that waits
# for the next line cannot tell a quiet research from a dead connection, and a
# proxy in front of it may time the connection out. One second is cheap - a
# comment line every second - and keeps intermediaries from growing impatient.
HEARTBEAT_SECONDS = 1.0

# A stream that has produced nothing for this long is closed, so a client that
# walked away does not leave a generator spinning forever.
IDLE_TIMEOUT_SECONDS = 300.0


def _not_found(exc: ResearchNotFound) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _event_frame(event) -> str:
    """One SSE frame, with the sequence as the event id.

    The id is the cursor. A client that reconnects sends the last id it saw and the
    server continues from there, so a disconnect costs the client nothing but the
    frames it had not received yet.
    """

    data = json.dumps(event.as_dict(), ensure_ascii=False)
    return f"id: {event.event_seq}\nevent: {event.kind}\ndata: {data}\n\n"


@router.get("/sessions/{thread_id}/research")
def list_thread_research(
    thread_id: str,
    feed: ResearchFeedDependency,
    limit: int = Query(default=20, ge=1, le=100),
):
    """The researches of one thread and nothing else.

    This is the endpoint a client opens when it wants to see what a chat is doing.
    It is a snapshot, not a stream: a client that wants to follow along opens the
    event stream afterwards.
    """

    snapshots = feed.thread_snapshot(thread_id, limit=limit)
    return {
        "thread_id": thread_id,
        "researches": [snapshot.as_dict() for snapshot in snapshots],
    }


@router.get("/sessions/{thread_id}/research/events")
async def stream_thread_research_events(
    thread_id: str,
    request: Request,
    feed: ResearchFeedDependency,
    after_event_seq: int = Query(default=0, ge=0),
):
    """Follow one thread's research. Read-only, and safe to leave.

    On disconnect this endpoint removes its subscription and returns. It does not
    cancel the research, does not interrupt anything, and does not write to any
    research row. The research is advanced by the coordinator from database facts,
    and the fact that nobody is watching changes nothing about it.
    """

    # The cursor lives in a one-element list rather than a plain local: the
    # generator below advances it, and a plain local assigned inside a nested
    # function is a *different* variable to Python - the outer one would stay at
    # its initial value and the stream would re-send everything on every poll.
    cursor = [after_event_seq]
    header_cursor = request.headers.get("last-event-id", "").strip()
    if header_cursor.isdigit():
        cursor[0] = int(header_cursor)

    registry = feed.registry
    handle = registry.subscribe(
        # A thread-wide subscription: the client is watching the chat, and it
        # does not yet know which of the chat's researches it will see. The
        # empty research id is what makes it thread-scoped rather than
        # research-scoped.
        research_id="",
        thread_id=thread_id,
        after_event_seq=cursor[0],
    )

    async def events() -> AsyncIterator[str]:
        try:
            idle = 0.0
            since_heartbeat = 0.0
            while True:
                if await request.is_disconnected():
                    # The subscription ends here. The research does not.
                    return
                # Do not advance a global cursor while iterating each research:
                # research A's event 3 would conceal research B's event 2.
                batch = feed.thread_events_since(thread_id, after_event_seq=cursor[0])
                for event in batch:
                    cursor[0] = event.event_seq
                    since_heartbeat = 0.0
                    yield _event_frame(event)
                states = feed.repository.list_by_thread(thread_id)
                # Drain paged events before declaring the thread idle.
                if (
                    states
                    and all(state.terminal for state in states)
                    and len(batch) < feed.limit
                ):
                    yield "event: research_idle\ndata: {}\n\n"
                    return
                since_heartbeat += POLL_SECONDS
                if since_heartbeat >= HEARTBEAT_SECONDS:
                    # A heartbeat keeps the connection demonstrably alive while
                    # nothing is happening. Without it a client - or a proxy in
                    # front of it - cannot tell "quiet" from "dead", and a reader
                    # that waits for the next line waits forever.
                    since_heartbeat = 0.0
                    yield "event: heartbeat\ndata: {}\n\n"
                await asyncio.sleep(POLL_SECONDS)
                idle += POLL_SECONDS
                if idle >= IDLE_TIMEOUT_SECONDS:
                    return
        finally:
            registry.unsubscribe(handle)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/research/{research_id}")
def get_research(
    research_id: str,
    feed: ResearchFeedDependency,
    after_event_seq: int = Query(default=0, ge=0),
):
    """One research: its state, its finished rounds, and what a client missed."""

    try:
        snapshot = feed.snapshot(research_id, after_event_seq=after_event_seq)
    except ResearchNotFound as exc:
        raise _not_found(exc) from None
    return snapshot.as_dict()


__all__ = ["POLL_SECONDS", "router"]
