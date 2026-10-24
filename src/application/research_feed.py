"""CL-M3 QD-3c: the subscription desk - watching a research without owning it.

This module is the answer to one question: *what may a client do that is not
"end the research"?*

The contract's R-3 says a research must not be lost because the user changed chat,
refreshed the page or lost an ordinary SSE connection - only an explicit user
cancellation or a policy termination may end it. The repository and the coordinator
already honour that: the coordinator advances research from database facts, and no
HTTP connection is part of that.

What was missing is the other half - the *reader's* side of the same rule. The
repository had no way to ask "what did this client miss", and the application had no
way to be told about a client's presence without also giving it the power to end
the research.

So this module separates three things that the existing code had folded together:

**A subscription is a cursor and a thread, and nothing else.** ``ResearchSubscription``
lives in the domain layer and deliberately has no ``cancel``. A client that stops
watching has stopped watching.

**The registry holds subscriptions, not research.** ``ResearchSubscriptionRegistry``
is an in-process table of who is watching what. It has no method that ends a
research, because ending a research is not something a reader may do. It is
explicitly *not* authoritative: a restarted process loses it, and that is fine,
because a reconnecting client re-subscribes with the cursor it already holds.

**The feed is the read side.** ``ResearchFeed`` turns durable rows into what a
client sees: the current snapshot, and the events a client missed while it was
away. It reads the authoritative tables, so a client that never lost its
connection and a client that reconnects get *the same answer* - the reconnecting
one just also learns what happened in between.

The one thing this module deliberately does not do is decide when a research ends.
That belongs to the executor and, later, to the cancellation policy (QD-3d).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading

from src.domain.research_event import (
    MAX_EVENTS_PER_READ,
    ResearchEvent,
    ResearchSnapshot,
    ResearchSubscription,
)
from src.domain.research_state import ResearchRound
from src.repositories.research_state_repository import (
    ResearchNotFound,
    ResearchStateRepository,
)

_logger = logging.getLogger(__name__)

# How many events a single poll returns. The cap exists so that one research with a
# very long history cannot make a reconnecting client download the entire log in
# one go; the client polls again with the new cursor.
DEFAULT_FEED_LIMIT = MAX_EVENTS_PER_READ


@dataclass(frozen=True)
class SubscriptionHandle:
    """The registry's side of a subscription.

    It is a receipt, not a capability: it names a subscriber so that dropping it
    removes exactly one subscription and not the subscriber's others.

    ``research_id`` is empty for a thread-wide subscription - a client that
    watches a whole chat does not know which research it will be about, and it
    may be several. The thread is the scope in that case.
    """

    subscriber_id: str
    research_id: str
    thread_id: str
    after_event_seq: int = 0


class ResearchSubscriptionRegistry:
    """Who is watching which research. In-process, and never authoritative.

    The registry exists so that the application can tell "nobody is watching" from
    "somebody is watching", which is useful for diagnostics and for deciding
    whether a wake-up is worth doing. It is *not* the queue and it is *not* the
    authority on a research's state: the database is.

    The absence of a cancel method is the whole point. There is deliberately no way
    from this object to end a research, so no code holding a registry can end one
    by accident. Cancellation is a separate, explicit, user-initiated path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscriptions: dict[str, SubscriptionHandle] = {}
        self._counter = 0

    def subscribe(
        self,
        *,
        research_id: str,
        thread_id: str,
        after_event_seq: int = 0,
        subscriber_id: str = "",
    ) -> SubscriptionHandle:
        """Register interest in a research. Says nothing about the research."""

        with self._lock:
            self._counter += 1
            handle_id = subscriber_id or f"subscriber-{self._counter}"
            handle = SubscriptionHandle(
                subscriber_id=handle_id,
                research_id=research_id,
                thread_id=thread_id,
                after_event_seq=after_event_seq,
            )
            self._subscriptions[handle_id] = handle
            return handle

    def unsubscribe(self, handle: SubscriptionHandle) -> None:
        """Stop watching. The research is unaffected - that is the entire contract."""

        with self._lock:
            self._subscriptions.pop(handle.subscriber_id, None)

    def drop_thread(self, thread_id: str) -> int:
        """Stop watching everything in a thread. Returns how many were dropped.

        This is what happens when the user switches chat. The researches of that
        thread keep running; only the watchers go away.
        """

        with self._lock:
            dropped = [
                key
                for key, handle in self._subscriptions.items()
                if handle.thread_id == thread_id
            ]
            for key in dropped:
                del self._subscriptions[key]
            return len(dropped)

    def watchers(self, research_id: str) -> int:
        """How many subscriptions are scoped to one research.

        A thread-wide subscription is not counted here: it does not name a
        research, and counting it against every research of its thread would
        make the number wrong in both directions.
        """

        with self._lock:
            return sum(
                1
                for handle in self._subscriptions.values()
                if handle.research_id == research_id
            )

    def watchers_of_thread(self, thread_id: str) -> int:
        """How many subscriptions are watching a whole thread."""

        with self._lock:
            return sum(
                1
                for handle in self._subscriptions.values()
                if handle.thread_id == thread_id
            )

    def handles(self) -> tuple[SubscriptionHandle, ...]:
        with self._lock:
            return tuple(self._subscriptions.values())


class ResearchFeed:
    """The read side: what a client sees, and what it missed while it was away."""

    def __init__(
        self,
        repository: ResearchStateRepository,
        *,
        registry: ResearchSubscriptionRegistry | None = None,
        limit: int = DEFAULT_FEED_LIMIT,
    ) -> None:
        self.repository = repository
        self.registry = registry or ResearchSubscriptionRegistry()
        self.limit = max(1, int(limit))

    def snapshot(
        self,
        research_id: str,
        *,
        after_event_seq: int = 0,
    ) -> ResearchSnapshot:
        """The current state, the finished rounds, and the events after a cursor.

        The state and the rounds come from the authoritative tables. The events are
        the tail. A client that never disconnected reads the same snapshot and
        simply finds the tail empty.
        """

        state = self.repository.load(research_id)
        if state is None:
            raise ResearchNotFound("research_not_found")
        rounds = self.repository.rounds(research_id)
        events = self.repository.events(
            research_id, after_event_seq=after_event_seq, limit=self.limit
        )
        # A count, not ``total - cursor``: the sequence is global, so subtracting
        # would count the other researches' events that sit in between.
        missed = self.repository.count_events_after(research_id, after_event_seq)
        return ResearchSnapshot(
            research_id=state.research_id,
            thread_id=state.thread_id,
            status=state.status,
            round_index=state.round_index,
            question=state.question,
            stop_reason=state.stop_reason,
            state_version=state.state_version,
            updated_at=state.updated_at,
            rounds=rounds,
            events=events,
            missed_events=missed,
        )

    def thread_snapshot(
        self, thread_id: str, *, limit: int = 20
    ) -> tuple[ResearchSnapshot, ...]:
        """Every research of one thread. Nothing from any other thread.

        This is the boundary that makes "switching chat does not disturb the other
        research" true by construction: a thread's view cannot contain another
        thread's research.
        """

        snapshots = []
        for state in self.repository.list_by_thread(thread_id, limit=limit):
            snapshots.append(
                ResearchSnapshot(
                    research_id=state.research_id,
                    thread_id=state.thread_id,
                    status=state.status,
                    round_index=state.round_index,
                    question=state.question,
                    stop_reason=state.stop_reason,
                    state_version=state.state_version,
                    updated_at=state.updated_at,
                    rounds=self.repository.rounds(state.research_id),
                    events=(),
                    missed_events=0,
                )
            )
        return tuple(snapshots)

    def events_since(
        self, research_id: str, *, after_event_seq: int = 0
    ) -> tuple[ResearchEvent, ...]:
        """The events a client missed. The cursor is exclusive."""

        return self.repository.events(
            research_id, after_event_seq=after_event_seq, limit=self.limit
        )

    def thread_events_since(
        self, thread_id: str, *, after_event_seq: int = 0
    ) -> tuple[ResearchEvent, ...]:
        """A single ordered global cursor across researches of one thread."""
        return self.repository.thread_events(
            thread_id, after_event_seq=after_event_seq, limit=self.limit
        )

    def poll(
        self,
        subscription: ResearchSubscription,
        *,
        limit: int | None = None,
    ) -> tuple[ResearchEvent, ...]:
        """Read what happened since the subscription's cursor.

        This is the polling shape the existing SSE route already uses for research
        progress. It was chosen over a push model for the same reason: the database
        is the queue, and a poller that loses its connection loses nothing.
        """

        return self.repository.events(
            subscription.research_id,
            after_event_seq=subscription.after_event_seq,
            limit=limit or self.limit,
        )


def rounds_to_payload(rounds: tuple[ResearchRound, ...]) -> list[dict[str, object]]:
    """A compact, JSON-safe view of finished rounds for an event payload.

    Kept here rather than in the domain module because it is a transport concern:
    the domain's ``ResearchRound`` is richer than anything a client needs.
    """

    return [
        {
            "round_index": record.round_index,
            "question": record.question,
            "queries": list(record.queries),
            "observation_urls": list(record.observation_urls),
            "evidence": list(record.evidence),
            "stop_reason": record.stop_reason,
        }
        for record in rounds
    ]


__all__ = [
    "DEFAULT_FEED_LIMIT",
    "ResearchFeed",
    "ResearchSubscriptionRegistry",
    "SubscriptionHandle",
    "rounds_to_payload",
]
