"""CL-M3 QD-3d: the durable records of cancellation, progress and authorisation.

Version 29. 25 belongs to the AR line, 26 to #259's spend ledger, 27 to
QD-3a's research state, 28 to QD-3c's event log. A migration number is a
permanent allocation, and 29 was checked against the other live branches
before being taken.

**Why the authorisation gets its own table.** ``research_states`` already
carries ``quota_observed`` - what was left of a budget when the checkpoint was
written. That is an *observation*, and it is rewritten on every checkpoint. An
authorisation is a *decision*: it has an author, a moment, an expiry and a
ceiling, and it has to survive long enough to be audited. Putting the two in
one column would mean the next checkpoint erased the record of who approved
what, and §10.8's fourth criterion - "升档必须留下用户授权记录" - would be
satisfied by a field a routine write overwrites.

So the request and the decision are two rows in a table of their own, and the
state row keeps a single boolean that says "this research's tier was raised
under a recorded authorisation". That boolean is a receipt, not the
authority: the authority is the row.

**Why the request is a separate row from the decision.** Because a request is
not an approval. The model may *ask* to spend more; only the user may
*grant* it. If one row held both, the asking would be indistinguishable from
the granting, and the first thing a reader could not tell apart would be the
one that costs money.

**The status may only move through a user's action.** ``pending`` becomes
``approved``/``denied`` by an explicit decision, and ``expired`` by the clock
alone. There is no path from ``pending`` to ``approved`` that does not name
who decided.
"""

from __future__ import annotations


RESEARCH_TIER_MIGRATION_V29 = """
ALTER TABLE research_states
    ADD COLUMN cancel_requested_at TEXT NOT NULL DEFAULT '';
ALTER TABLE research_states
    ADD COLUMN tier_upgrade_authorized INTEGER NOT NULL DEFAULT 0;
ALTER TABLE research_states
    ADD COLUMN in_flight_calls INTEGER NOT NULL DEFAULT 0;
ALTER TABLE research_states
    ADD COLUMN observed_calls INTEGER NOT NULL DEFAULT 0;

CREATE TABLE research_tier_upgrade_requests (
    request_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_states(research_id),
    operation_id TEXT NOT NULL,
    from_tier TEXT NOT NULL,
    to_tier TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    requested_calls INTEGER NOT NULL DEFAULT 0,
    requested_cost REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL
);

CREATE INDEX idx_tier_requests_research
    ON research_tier_upgrade_requests(research_id, status);

CREATE TABLE research_tier_authorizations (
    request_id TEXT PRIMARY KEY
        REFERENCES research_tier_upgrade_requests(request_id),
    research_id TEXT NOT NULL REFERENCES research_states(research_id),
    operation_id TEXT NOT NULL,
    status TEXT NOT NULL,
    approver TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    valid_until TEXT NOT NULL DEFAULT '',
    max_calls INTEGER NOT NULL DEFAULT 0,
    max_cost REAL NOT NULL DEFAULT 0,
    decided_at TEXT NOT NULL DEFAULT '',
    requested_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_tier_authorizations_research
    ON research_tier_authorizations(research_id, status);
"""
