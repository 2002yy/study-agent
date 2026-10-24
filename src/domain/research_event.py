"""CL-M3 QD-3c: the durable vocabulary of what a reconnecting client missed.

QD-3a made a research durable and QD-3b made something advance it. Neither of them
answered the question a browser asks when it comes back: *what happened while I was
gone?*

That question needs three things, and this module holds all three.

**A cursor that survives a disconnect.** ``event_seq`` is allocated by the database
per research and never reused. A client that reconnects says "I have seen up to
``event_seq`` N" and receives everything after N. The sequence is per research
because a client watches one research at a time; the thread-level view composes
several of these.

**An event that says what happened, not what is true.** ``kind`` names the kind of
event and ``payload`` carries its detail. Neither is an authority. The authority for
"what is the state now" is ``research_states``; the authority for "which rounds
finished" is ``research_rounds``. This distinction is load-bearing: if the event log
were the authority, deleting it would change what a research *is*, and a client that
reconnected after the log was pruned would be told a different story than one that
never disconnected.

**A subscription that can end without ending the research.** ``ResearchSubscription``
is what a client holds while it is watching. Closing it ends the watching. Nothing
about closing it says anything about the research, and the type carries no method
that could: there is deliberately no ``cancel`` on it. A research ends because the
executor decided it ended (QD-3d owns the policy), not because a browser tab closed.

That last point is why this module exists separately from ``research_state``. The
contract's R-3 says a research must not be lost because the user changed chat,
refreshed the page or lost an ordinary SSE connection - only an explicit user
cancellation or a policy termination may end it. The type system is where that rule
is cheapest to enforce: a subscription that cannot cancel anything cannot accidentally
cancel something.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from src.domain.research_state import ResearchRound

# The kinds of event a research emits. They are a closed set on purpose: an event
# kind is a contract with the client, and a client that has to handle an unknown kind
# is a client that was not written for this version.
EVENT_RESEARCH_STARTED = "research_started"
EVENT_ROUND_COMPLETED = "round_completed"
EVENT_RESEARCH_FINISHED = "research_finished"
EVENT_KINDS = frozenset(
    {
        EVENT_RESEARCH_STARTED,
        EVENT_ROUND_COMPLETED,
        EVENT_RESEARCH_FINISHED,
    }
)

# A payload is a small JSON object. The cap keeps an event from becoming a second
# copy of the round: the round's evidence lives in ``research_rounds`` and the event
# points at it.
MAX_PAYLOAD_BYTES = 8192
MAX_EVENTS_PER_READ = 500


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid_{name}")
    return value


@dataclass(frozen=True)
class ResearchEvent:
    """One durable thing that happened to a research."""

    research_id: str
    event_seq: int
    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        _text(self.research_id, "research_id", 160)
        if type(self.event_seq) is not int or self.event_seq < 1:
            raise ValueError("invalid_event_seq")
        if self.kind not in EVENT_KINDS:
            raise ValueError("invalid_event_kind")
        if not isinstance(self.payload, Mapping):
            raise ValueError("invalid_event_payload")
        encoded = json.dumps(dict(self.payload), ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("event_payload_exceeds_cap")
        if not isinstance(self.created_at, str) or len(self.created_at) > 200:
            raise ValueError("invalid_event_created_at")

    @property
    def round_index(self) -> int:
        """Which round this event is about, or ``-1`` when it is not about one.

        ``-1`` rather than ``0``: round 0 is a real round that a real research ran,
        and a client must not be unable to tell "the first round" from "no round".
        """

        value = self.payload.get("round_index")
        if type(value) is not int or value < 0:
            return -1
        return value

    def as_dict(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "event_seq": self.event_seq,
            "kind": self.kind,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchSubscription:
    """A client's live view of one research.

    It carries no power. There is no ``cancel`` on this type, and that is the point:
    a subscription that could end its research would make "the browser tab closed"
    indistinguishable from "the user cancelled", which is exactly the confusion
    R-3 forbids. Closing a subscription is done by dropping it.
    """

    research_id: str
    thread_id: str
    after_event_seq: int = 0
    subscriber_id: str = ""

    def __post_init__(self) -> None:
        _text(self.research_id, "research_id", 160)
        _text(self.thread_id, "thread_id", 160)
        if type(self.after_event_seq) is not int or self.after_event_seq < 0:
            raise ValueError("invalid_after_event_seq")
        if not isinstance(self.subscriber_id, str) or len(self.subscriber_id) > 160:
            raise ValueError("invalid_subscriber_id")

    def resumed_at(self, event: ResearchEvent) -> int:
        """The cursor a client should hold after receiving this event."""

        return event.event_seq


@dataclass(frozen=True)
class ResearchSnapshot:
    """Everything a client needs to draw a research, read once.

    The state and the finished rounds come from the authoritative tables. The events
    are the tail a reconnecting client may or may not need. A client that never
    disconnected reads the state; a client that did reads the events it missed and
    then reads the state, which is the same state either way.
    """

    research_id: str
    thread_id: str
    status: str
    round_index: int
    question: str
    stop_reason: str = ""
    state_version: int = 1
    updated_at: str = ""
    rounds: tuple[ResearchRound, ...] = ()
    events: tuple[ResearchEvent, ...] = ()
    missed_events: int = 0

    def __post_init__(self) -> None:
        _text(self.research_id, "research_id", 160)
        _text(self.thread_id, "thread_id", 160)
        if type(self.round_index) is not int or self.round_index < 0:
            raise ValueError("invalid_snapshot_round_index")
        if type(self.state_version) is not int or self.state_version < 1:
            raise ValueError("invalid_snapshot_state_version")
        if type(self.missed_events) is not int or self.missed_events < 0:
            raise ValueError("invalid_snapshot_missed_events")
        if not isinstance(self.rounds, tuple):
            raise ValueError("invalid_snapshot_rounds")
        if not isinstance(self.events, tuple):
            raise ValueError("invalid_snapshot_events")

    def as_dict(self) -> dict[str, Any]:
        return {
            "research_id": self.research_id,
            "thread_id": self.thread_id,
            "status": self.status,
            "round_index": self.round_index,
            "question": self.question,
            "stop_reason": self.stop_reason,
            "state_version": self.state_version,
            "updated_at": self.updated_at,
            "rounds": [
                {
                    "round_index": record.round_index,
                    "question": record.question,
                    "queries": list(record.queries),
                    "observation_urls": list(record.observation_urls),
                    "evidence": list(record.evidence),
                    "stop_reason": record.stop_reason,
                    "created_at": record.created_at,
                }
                for record in self.rounds
            ],
            "events": [event.as_dict() for event in self.events],
            "missed_events": self.missed_events,
        }


__all__ = [
    "EVENT_KINDS",
    "EVENT_RESEARCH_FINISHED",
    "EVENT_RESEARCH_STARTED",
    "EVENT_ROUND_COMPLETED",
    "MAX_EVENTS_PER_READ",
    "MAX_PAYLOAD_BYTES",
    "ResearchEvent",
    "ResearchSnapshot",
    "ResearchSubscription",
]
