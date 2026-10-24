"""CL-M3 QD-3a: read/write the durable research state under compare-and-swap.

The only hard problem here is that two workers may believe they own the same research. Every
write in this module therefore carries the writer's own identity and the state version it
read, and the database decides - not the caller, and not the process that happens to still
have an object in memory.

Why fencing tokens rather than just an owner name: a worker whose lease expired, was taken
over, and then re-acquired under the same owner name would be indistinguishable from the
original by name alone. The token increments on every claim, so "the same name, one
generation later" is a different writer and its late writes are refused.

Why ``state_version`` as well: the token protects across claims, the version protects within
one. Both are cheap, and either alone leaves a hole - a worker can hold a valid token and
still be writing about a round that has already moved on.

Nothing here settles money, and nothing here counts it. ``quota_observed`` is written
monotonically downwards for the same reason a checkpoint may not raise a budget: a resumed
worker that could raise its own ceiling would have found a refund.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
import sqlite3
from typing import Any, Mapping

from src.domain.research_event import (
    EVENT_RESEARCH_FINISHED,
    EVENT_ROUND_COMPLETED,
    MAX_EVENTS_PER_READ,
    ResearchEvent,
)
from src.domain.research_state import (
    MAX_FOLDED_FACTS,
    RESEARCH_REQUEST_SCHEMA,
    ResearchResume,
    ResearchRound,
    ResearchState,
    quota,
    research_request_key,
)
from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase

DEFAULT_LEASE_SECONDS = 90.0
MAX_LEASE_SECONDS = 3600.0


class ResearchNotFound(ValueError):
    """No research with that id."""


class ResearchAlreadyTerminal(ValueError):
    """The research stopped, was cancelled or failed; nothing may claim it again."""


class ResearchLeaseHeld(ValueError):
    """Another worker holds a live lease. Waiting is the caller's decision, not ours."""


class StaleResearchWriter(RuntimeError):
    """This writer's lease or version was superseded.

    Raised instead of silently doing nothing: a worker that keeps computing on a research it
    no longer owns is the failure this whole module exists to prevent, and it must learn
    about it at the write, not at shutdown.
    """


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(raw: Any, fallback: Any) -> Any:
    if not isinstance(raw, str) or not raw:
        return fallback
    try:
        return json.loads(raw)
    except ValueError:
        raise ValueError("corrupt_research_state") from None


def _identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError(f"invalid_{name}")
    return value


def _lease_ttl(seconds: Any) -> float:
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not 0 < float(seconds) <= MAX_LEASE_SECONDS
    ):
        raise ValueError("invalid_lease_seconds")
    return float(seconds)


def _expiry(now: str, ttl: float) -> str:
    return (datetime.fromisoformat(now) + timedelta(seconds=ttl)).isoformat()


class ResearchStateRepository:
    """Durable research facts; no scheduling and no execution live here."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database

    # --- reads --------------------------------------------------------------------

    def load(self, research_id: str) -> ResearchState | None:
        _identity(research_id, "research_id")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_states WHERE research_id = ?", (research_id,)
            ).fetchone()
        return None if row is None else _state_from_row(row)

    def rounds(self, research_id: str) -> tuple[ResearchRound, ...]:
        _identity(research_id, "research_id")
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_rounds WHERE research_id = ? "
                "ORDER BY round_index ASC",
                (research_id,),
            ).fetchall()
        return tuple(_round_from_row(row) for row in rows)

    def resume(self, research_id: str) -> ResearchResume | None:
        """Everything needed to continue: state plus every finished round, in order."""
        state = self.load(research_id)
        if state is None:
            return None
        return ResearchResume(state, self.rounds(research_id))

    def snapshot_parts(
        self,
        research_id: str,
        *,
        after_event_seq: int = 0,
        limit: int = MAX_EVENTS_PER_READ,
    ) -> tuple[ResearchState, tuple[ResearchRound, ...], tuple[ResearchEvent, ...], int]:
        """Read state, rounds, event tail and missed count from ONE SQLite snapshot.

        A checkpoint commits state + round + event atomically. Separate read
        connections can still straddle that commit and report a state from before
        it alongside rounds from after it. BEGIN anchors all four SELECTs to
        the same consistent snapshot without taking an immediate writer lock.
        """
        _identity(research_id, "research_id")
        if type(after_event_seq) is not int or after_event_seq < 0:
            raise ValueError("invalid_after_event_seq")
        if type(limit) is not int or limit < 1 or limit > MAX_EVENTS_PER_READ:
            raise ValueError("invalid_event_limit")
        with self.database.connect() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM research_states WHERE research_id = ?", (research_id,)
            ).fetchone()
            if row is None:
                raise ResearchNotFound("research_not_found")
            round_rows = connection.execute(
                "SELECT * FROM research_rounds WHERE research_id = ? "
                "ORDER BY round_index ASC", (research_id,)
            ).fetchall()
            event_rows = connection.execute(
                "SELECT * FROM research_events WHERE research_id = ? AND event_seq > ? "
                "ORDER BY event_seq ASC LIMIT ?",
                (research_id, after_event_seq, limit),
            ).fetchall()
            missed = connection.execute(
                "SELECT COUNT(*) AS total FROM research_events "
                "WHERE research_id = ? AND event_seq > ?",
                (research_id, after_event_seq),
            ).fetchone()
            # COUNT(*) always returns exactly one row. Treat an absent row as
            # an invalid read, not an invented zero-event snapshot.
            if missed is None:
                raise RuntimeError("research_snapshot_count_unavailable")
        return (
            _state_from_row(row),
            tuple(_round_from_row(item) for item in round_rows),
            tuple(_event_from_row(item) for item in event_rows),
            int(missed["total"]),
        )

    def resumable(self, *, limit: int = 16, now: str | None = None) -> tuple[ResearchState, ...]:
        """Research that may be claimed right now. A live lease is not offered."""
        if type(limit) is not int or limit < 0:
            raise ValueError("invalid_resumable_limit")
        moment = now or utc_now()
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_states "
                "WHERE status IN ('running', 'checkpointed') "
                "AND (lease_owner = '' OR lease_expires_at <= ?) "
                "ORDER BY updated_at ASC, research_id ASC LIMIT ?",
                (moment, limit),
            ).fetchall()
        return tuple(_state_from_row(row) for row in rows)

    # --- create -------------------------------------------------------------------

    def create(
        self,
        *,
        research_id: str,
        thread_id: str,
        operation_id: str,
        original_question: str,
        question: str,
        tier: str,
        quota_observed: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> ResearchState:
        """Insert the first version. The same id twice is refused rather than replaced."""
        moment = now or utc_now()
        state = ResearchState(
            research_id=_identity(research_id, "research_id"),
            thread_id=_identity(thread_id, "thread_id"),
            operation_id=_identity(operation_id, "operation_id"),
            original_question=original_question,
            question=question,
            tier=tier,
            quota_observed=quota(quota_observed),
            created_at=moment,
            updated_at=moment,
        )
        with self.database.connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO research_states ("
                    "research_id, thread_id, operation_id, original_question, question, "
                    "tier, round_index, status, stop_reason, evidence, quota_observed, "
                    "state_version, lease_owner, lease_expires_at, fencing_token, "
                    "created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, 0, ?, '', '[]', ?, 1, '', '', 0, ?, ?)",
                    (
                        state.research_id,
                        state.thread_id,
                        state.operation_id,
                        state.original_question,
                        state.question,
                        state.tier,
                        state.status,
                        _dump(dict(state.quota_observed)),
                        moment,
                        moment,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ValueError("research_already_exists") from None
        return state

    # --- lease --------------------------------------------------------------------

    def claim(
        self,
        research_id: str,
        *,
        owner: str,
        ttl_seconds: float = DEFAULT_LEASE_SECONDS,
        now: str | None = None,
    ) -> ResearchState:
        """Take or take over the lease. Every successful claim bumps the fencing token."""
        _identity(research_id, "research_id")
        _identity(owner, "lease_owner")
        ttl = _lease_ttl(ttl_seconds)
        moment = now or utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE research_states "
                "SET lease_owner = ?, lease_expires_at = ?, "
                "fencing_token = fencing_token + 1, status = 'running', updated_at = ? "
                "WHERE research_id = ? "
                "AND status IN ('running', 'checkpointed') "
                "AND (lease_owner = '' OR lease_expires_at <= ?)",
                (owner, _expiry(moment, ttl), moment, research_id, moment),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT status, lease_owner, lease_expires_at FROM research_states "
                    "WHERE research_id = ?",
                    (research_id,),
                ).fetchone()
                if row is None:
                    raise ResearchNotFound("research_not_found")
                if row["status"] not in {"running", "checkpointed"}:
                    raise ResearchAlreadyTerminal("research_already_terminal")
                raise ResearchLeaseHeld("research_lease_held")
        state = self.load(research_id)
        if state is None:  # pragma: no cover - the row cannot vanish mid-call
            raise ResearchNotFound("research_not_found")
        return state

    def renew(
        self,
        research_id: str,
        *,
        owner: str,
        fencing_token: int,
        ttl_seconds: float = DEFAULT_LEASE_SECONDS,
        now: str | None = None,
    ) -> ResearchState:
        """Extend this worker's lease. Refused once it has been taken over."""
        _identity(research_id, "research_id")
        _identity(owner, "lease_owner")
        ttl = _lease_ttl(ttl_seconds)
        moment = now or utc_now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE research_states SET lease_expires_at = ?, updated_at = ? "
                "WHERE research_id = ? AND lease_owner = ? AND fencing_token = ?",
                (_expiry(moment, ttl), moment, research_id, owner, fencing_token),
            )
            if cursor.rowcount != 1:
                raise StaleResearchWriter("research_lease_superseded")
        state = self.load(research_id)
        if state is None:  # pragma: no cover
            raise ResearchNotFound("research_not_found")
        return state

    def release(self, research_id: str, *, owner: str, fencing_token: int) -> None:
        """Give the lease back early, so a clean shutdown does not wait out the TTL.

        A release from a superseded worker is ignored rather than refused: the lease is
        already someone else's, and clearing it would steal it back.
        """
        _identity(research_id, "research_id")
        _identity(owner, "lease_owner")
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE research_states SET lease_owner = '', lease_expires_at = '' "
                "WHERE research_id = ? AND lease_owner = ? AND fencing_token = ?",
                (research_id, owner, fencing_token),
            )

    # --- checkpoint ---------------------------------------------------------------

    def checkpoint(
        self,
        research_id: str,
        round_record: ResearchRound,
        *,
        owner: str,
        fencing_token: int,
        expected_state_version: int,
        question: str | None = None,
        status: str = "checkpointed",
        stop_reason: str | None = None,
        quota_observed: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> ResearchState:
        """Append one round and advance the state, atomically or not at all.

        The round row and the state row are written in one transaction, so a reader can never
        see "round 3 exists but the state still says 2". If the compare-and-swap misses - a
        takeover, a version another writer already advanced, a duplicate round - the round
        row is rolled back with it rather than left as evidence of work nobody owns.
        """
        _identity(research_id, "research_id")
        _identity(owner, "lease_owner")
        if not isinstance(round_record, ResearchRound):
            raise ValueError("invalid_research_round")
        if round_record.research_id != research_id:
            raise ValueError("research_round_owner_mismatch")
        if type(expected_state_version) is not int or expected_state_version < 1:
            raise ValueError("invalid_state_version")
        moment = now or utc_now()
        observed = quota(quota_observed)

        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT round_index, state_version, quota_observed FROM research_states "
                "WHERE research_id = ?",
                (research_id,),
            ).fetchone()
            if current is None:
                raise ResearchNotFound("research_not_found")
            if round_record.round_index != current["round_index"]:
                raise StaleResearchWriter("research_round_out_of_order")
            # Monotonic: a checkpoint may hold the budget flat or lower it, never raise it.
            previous = _load(current["quota_observed"], {})
            for key, value in observed.items():
                if type(previous.get(key)) is int and value > previous[key]:
                    raise ValueError(f"quota_may_not_increase:{key}")

            connection.execute(
                "INSERT INTO research_rounds ("
                "research_id, round_index, question, queries, observation_urls, "
                "evidence, stop_reason, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    research_id,
                    round_record.round_index,
                    round_record.question,
                    _dump(list(round_record.queries)),
                    _dump(list(round_record.observation_urls)),
                    _dump(list(round_record.evidence)),
                    round_record.stop_reason,
                    round_record.created_at or moment,
                ),
            )
            cursor = connection.execute(
                "UPDATE research_states SET "
                "round_index = round_index + 1, question = ?, status = ?, stop_reason = ?, "
                "evidence = ?, quota_observed = ?, state_version = state_version + 1, "
                "lease_owner = CASE WHEN ? IN ('stopped','cancelled','failed') "
                "THEN '' ELSE lease_owner END, "
                "lease_expires_at = CASE WHEN ? IN ('stopped','cancelled','failed') "
                "THEN '' ELSE lease_expires_at END, "
                "updated_at = ? "
                "WHERE research_id = ? AND lease_owner = ? AND fencing_token = ? "
                "AND state_version = ?",
                (
                    question if question is not None else round_record.question,
                    status,
                    round_record.stop_reason if stop_reason is None else stop_reason,
                    _dump(list(round_record.evidence)),
                    _dump(observed or previous),
                    status,
                    status,
                    moment,
                    research_id,
                    owner,
                    fencing_token,
                    expected_state_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StaleResearchWriter("research_state_superseded")

            # The event is written in this same transaction as the round. If the
            # round were committed and the event left for a second write, a crash
            # between the two would leave a research whose client can never learn
            # that the round happened - which is precisely the loss §10.8's first
            # acceptance criterion is about.
            self._append_event(
                connection,
                research_id,
                kind=EVENT_ROUND_COMPLETED,
                payload={
                    "round_index": round_record.round_index,
                    "status": status,
                    "stop_reason": round_record.stop_reason if stop_reason is None else stop_reason,
                },
                now=moment,
            )
            if status in {"stopped", "cancelled", "failed"}:
                self._append_event(
                    connection,
                    research_id,
                    kind=EVENT_RESEARCH_FINISHED,
                    payload={
                        "round_index": round_record.round_index,
                        "status": status,
                        "stop_reason": round_record.stop_reason if stop_reason is None else stop_reason,
                    },
                    now=moment,
                )
        state = self.load(research_id)
        if state is None:  # pragma: no cover
            raise ResearchNotFound("research_not_found")
        return state

    # --- events --------------------------------------------------------------------

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        research_id: str,
        *,
        kind: str,
        payload: Mapping[str, Any],
        now: str,
    ) -> int:
        """Append one event and return its sequence.

        The sequence comes from the database's ``AUTOINCREMENT`` counter, not from
        the caller and not from a ``MAX() + 1`` read. Two reasons, both learned the
        hard way:

        - A read-then-insert would let two writers read the same maximum and mint
          the same number, and the second insert would die on the unique
          constraint. A cursor that skipped an event because of a write collision
          is exactly the loss this table exists to prevent.
        - The counter is global, not per research. A client watches a thread and
          holds one cursor, so the events of several researches must share one
          order; per-research numbering would make research B's event 1 look
          older than research A's event 5 to that cursor.
        """

        cursor = connection.execute(
            "INSERT INTO research_events ("
            "research_id, kind, payload, created_at"
            ") VALUES (?, ?, ?, ?)",
            (research_id, kind, _dump(dict(payload)), now),
        )
        return int(cursor.lastrowid)

    def append_event(
        self,
        research_id: str,
        *,
        kind: str,
        payload: Mapping[str, Any] | None = None,
        now: str | None = None,
    ) -> ResearchEvent:
        """Append one event outside a checkpoint.

        Used for the events that are not about a round - a research that started, a
        tier that was authorised. It is deliberately *not* how round events are
        written: those go through ``checkpoint`` so that they share its transaction.
        """

        _identity(research_id, "research_id")
        moment = now or utc_now()
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM research_states WHERE research_id = ?", (research_id,)
            ).fetchone()
            if exists is None:
                raise ResearchNotFound("research_not_found")
            event_seq = self._append_event(
                connection,
                research_id,
                kind=kind,
                payload=dict(payload or {}),
                now=moment,
            )
        return ResearchEvent(
            research_id=research_id,
            event_seq=event_seq,
            kind=kind,
            payload=dict(payload or {}),
            created_at=moment,
        )

    def events(
        self,
        research_id: str,
        *,
        after_event_seq: int = 0,
        limit: int = MAX_EVENTS_PER_READ,
    ) -> tuple[ResearchEvent, ...]:
        """Events after a cursor, oldest first. The cursor is exclusive."""

        _identity(research_id, "research_id")
        if type(after_event_seq) is not int or after_event_seq < 0:
            raise ValueError("invalid_after_event_seq")
        if type(limit) is not int or limit < 0:
            raise ValueError("invalid_event_limit")
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_events WHERE research_id = ? AND event_seq > ? "
                "ORDER BY event_seq ASC LIMIT ?",
                (research_id, after_event_seq, limit),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def thread_events(
        self,
        thread_id: str,
        *,
        after_event_seq: int = 0,
        limit: int = MAX_EVENTS_PER_READ,
    ) -> tuple[ResearchEvent, ...]:
        """One ordered cursor over *all* researches belonging to the thread.

        Never iterate per-research event streams while advancing a shared cursor:
        event_seq is global and a later event from research A can otherwise hide
        an earlier event from research B.
        """
        _identity(thread_id, "thread_id")
        if type(after_event_seq) is not int or after_event_seq < 0:
            raise ValueError("invalid_after_event_seq")
        if type(limit) is not int or limit < 1 or limit > MAX_EVENTS_PER_READ:
            raise ValueError("invalid_event_limit")
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT e.* FROM research_events AS e "
                "JOIN research_states AS s ON s.research_id = e.research_id "
                "WHERE s.thread_id = ? AND e.event_seq > ? "
                "ORDER BY e.event_seq ASC LIMIT ?",
                (thread_id, after_event_seq, limit),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def count_events(self, research_id: str) -> int:
        """How many events a research has in total."""

        _identity(research_id, "research_id")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM research_events WHERE research_id = ?",
                (research_id,),
            ).fetchone()
        return int(row["total"])

    def count_events_after(self, research_id: str, after_event_seq: int) -> int:
        """How many of this research's events are newer than a cursor.

        This is a count, not a subtraction. The sequence is global, so
        ``total - cursor`` would subtract the events of *other* researches that
        happen to sit between them - and a client that was told it missed three
        events would be shown two. The count is the only number that means what
        the client will read.
        """

        _identity(research_id, "research_id")
        if type(after_event_seq) is not int or after_event_seq < 0:
            raise ValueError("invalid_after_event_seq")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM research_events "
                "WHERE research_id = ? AND event_seq > ?",
                (research_id, after_event_seq),
            ).fetchone()
        return int(row["total"])

    def list_by_thread(
        self, thread_id: str, *, limit: int = 20
    ) -> tuple[ResearchState, ...]:
        """The researches that belong to a thread, most recently touched first.

        This is what a client reads when it opens a chat: the researches of *this*
        thread and nothing else. A thread is the unit the user thinks in, so it is
        also the unit a subscription is scoped to.
        """

        _identity(thread_id, "thread_id")
        if type(limit) is not int or limit < 0:
            raise ValueError("invalid_thread_limit")
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_states WHERE thread_id = ? "
                "ORDER BY updated_at DESC, research_id ASC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        return tuple(_state_from_row(row) for row in rows)


def _state_from_row(row: sqlite3.Row) -> ResearchState:
    return ResearchState(
        research_id=row["research_id"],
        thread_id=row["thread_id"],
        operation_id=row["operation_id"],
        original_question=row["original_question"],
        question=row["question"],
        tier=row["tier"],
        round_index=row["round_index"],
        status=row["status"],
        stop_reason=row["stop_reason"],
        evidence=tuple(_load(row["evidence"], [])),
        quota_observed=_load(row["quota_observed"], {}),
        state_version=row["state_version"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        fencing_token=row["fencing_token"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _round_from_row(row: sqlite3.Row) -> ResearchRound:
    return ResearchRound(
        research_id=row["research_id"],
        round_index=row["round_index"],
        question=row["question"],
        queries=tuple(_load(row["queries"], [])),
        observation_urls=tuple(_load(row["observation_urls"], [])),
        evidence=tuple(_load(row["evidence"], [])),
        stop_reason=row["stop_reason"],
        created_at=row["created_at"],
    )


def _event_from_row(row: sqlite3.Row) -> ResearchEvent:
    return ResearchEvent(
        research_id=row["research_id"],
        event_seq=row["event_seq"],
        kind=row["kind"],
        payload=_load(row["payload"], {}),
        created_at=row["created_at"],
    )


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "MAX_FOLDED_FACTS",
    "MAX_LEASE_SECONDS",
    "RESEARCH_REQUEST_SCHEMA",
    "ResearchAlreadyTerminal",
    "ResearchLeaseHeld",
    "ResearchNotFound",
    "ResearchStateRepository",
    "StaleResearchWriter",
    "research_request_key",
]
