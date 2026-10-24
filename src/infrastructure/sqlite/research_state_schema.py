"""CL-M3 QD-3a: durable research state and per-round checkpoints.

Version 27, not 25. The integration of #259 and the AR branch already claims 25
(``chat_turns.attachment_refs``) and 26 (``llm_spend_experiments`` /
``llm_spend_reservations``). A migration number is a permanent allocation: reusing one here
would not fail loudly, it would make the two branches apply different SQL under the same
version depending on merge order, and whichever landed second would silently skip the other.

**Two tables, because the two facts have different lifetimes.**

``research_states`` is the single mutable row per research: where it is now, what it may
spend, which worker owns it. It is updated by compare-and-swap, never blindly.

``research_rounds`` is append-only. A round that finished stays finished, and that is what a
reconnecting client reads to see "the rounds that already completed" instead of a status
field that only says "running". It also carries the round's own evidence, because the
planning episode (``ResearchEpisode``) is a *bounded, lossy* context - §7.5 of the contract
records that it drops ``attempts`` and ``source_leads`` under pressure - and a checkpoint
that inherited that behaviour would lose the observations the whole feature exists to keep.

**No money lives here.** ``quota_observed`` is a recorded observation for planning, not an
authority: the real ledger is #259, and a second table counting the same spend would be the
third ledger this project has twice refused to build. The repository enforces the one
property that keeps a resumed worker honest - a checkpoint may lower that observation but
never raise it.
"""

from __future__ import annotations


RESEARCH_STATE_MIGRATION_V27 = """
CREATE TABLE research_states (
    research_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    original_question TEXT NOT NULL,
    question TEXT NOT NULL,
    tier TEXT NOT NULL,
    round_index INTEGER NOT NULL DEFAULT 0 CHECK(round_index >= 0),
    status TEXT NOT NULL,
    stop_reason TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    quota_observed TEXT NOT NULL DEFAULT '{}',
    state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version >= 1),
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT NOT NULL DEFAULT '',
    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK(fencing_token >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_research_states_thread
    ON research_states(thread_id, updated_at DESC, research_id);

CREATE INDEX idx_research_states_resumable
    ON research_states(status, lease_expires_at);

CREATE TABLE research_rounds (
    research_id TEXT NOT NULL REFERENCES research_states(research_id),
    round_index INTEGER NOT NULL CHECK(round_index >= 0),
    question TEXT NOT NULL,
    queries TEXT NOT NULL DEFAULT '[]',
    observation_urls TEXT NOT NULL DEFAULT '[]',
    evidence TEXT NOT NULL DEFAULT '[]',
    stop_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (research_id, round_index)
);
"""
