"""CL-M3 QD-3c: durable research events - the cursor a reconnecting client needs.

Version 28. 25 belongs to the AR line, 26 to #259's spend ledger, 27 to QD-3a's
research state. A migration number is a permanent allocation, and 28 was checked
against the other live branches before being taken.

**Why a table at all.** The repository had no event log, so "reconnect and see what
you missed" had nowhere to read from. ``research_rounds`` is append-only but its
``round_index`` is monotonic *within one research*; it cannot order events across
researches, and a client watching a whole thread needs exactly that. ``state_version``
cannot be used either: it is a compare-and-swap version, so it skips numbers and
answers "who may write", not "what happened". A cursor that skips would make a
reconnecting client silently miss an event it had already been told about.

**Why the sequence is global, and allocated by the database.** Two separate
requirements point the same way.

*Global.* A client watches a thread, and a thread may hold several researches at
once. Their events have to share one order, because the client holds one cursor.
A per-research sequence cannot do that: research A's event 1 and research B's
event 1 are different numbers, and a cursor that has seen A's event 5 would skip
B's events 1 through 4. The sequence is therefore global.

*Allocated by the database.* ``AUTOINCREMENT`` hands out the numbers inside the
write transaction, so two writers cannot mint the same one. The obvious
alternative - ``SELECT MAX(event_seq) + 1`` followed by an ``INSERT`` - was tried
first and is wrong under concurrency: two writers read the same maximum and the
second insert dies on the unique constraint. A cursor that skipped an event
because of a write collision is exactly the failure this table exists to prevent.

``AUTOINCREMENT`` rather than a plain rowid for one more reason: a plain rowid
reuses the number of a deleted row, so a client holding cursor N could be sent
back to an event it had already seen. ``AUTOINCREMENT`` never reuses a number.

**This table is not a second truth.** The authority for "what is the state now" is
``research_states``; the authority for "which rounds finished" is ``research_rounds``.
The event log answers a narrower question - "what did this client miss" - and a
client that never lost its connection should read the state, not the log. That is
why the table carries a payload but no authoritative status: the state of a
research is never derived from its events.
"""

from __future__ import annotations


RESEARCH_EVENT_MIGRATION_V28 = """
CREATE TABLE research_events (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    research_id TEXT NOT NULL REFERENCES research_states(research_id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX idx_research_events_research
    ON research_events(research_id, event_seq);

CREATE INDEX idx_research_events_thread
    ON research_events(created_at DESC, research_id, event_seq);
"""
