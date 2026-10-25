"""CL-M3-S1: migration 30 - the append-only settlement audit.

The ledger's two tables (migration 26) answer "what was this run allowed to
spend, at most". This table answers a different question - "what did we later
learn about each of those sends" - and the contract
(``CL_M3_CAPABILITY_CONTRACT.md`` §12) keeps the two apart on purpose:

* a reservation is **never** updated, refunded or recalculated here;
* an observation is **append-only**: a correction is a new revision, never an
  ``UPDATE``, so the audit trail cannot be rewritten by a later, quieter claim;
* the current state is the highest ``revision``, and the only permitted
  transition is ``unresolved -> settled`` (once, with evidence).

**Why triggers and not only repository code.** "Append-only" is a property of
the data, not of the callers. A direct ``UPDATE``/``DELETE`` from a script, a
debug session or a future module must fail the same way the repository would
refuse it. The two triggers below make that true at the storage layer.

**Why a separate epoch row.** Migration 30 runs against databases that already
hold reservations. Those rows predate the audit layer: nobody failed to write
an observation for them, the concept did not exist yet. The recovery scan must
not report them as debt, so the migration records the highest reservation id it
saw, and the scan only considers rows above it. A watermark computed at
migration time is stable; a timestamp comparison would be a guess.

``evidence_ref`` on a ``settled`` row is the binding to the actual send:
``<kind>:<request_key>#<receipt>``. The CHECK here only guarantees a non-empty
string; the repository parses the grammar and rejects a reference that names a
different request.
"""

from __future__ import annotations


LLM_SPEND_SETTLEMENT_MIGRATION_V30 = """
CREATE TABLE llm_spend_settlements (
    experiment_id TEXT NOT NULL,
    request_key TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    outcome TEXT NOT NULL
        CHECK (outcome IN ('unresolved', 'settled', 'failed')),
    cost_micros INTEGER NULL
        CHECK (cost_micros IS NULL OR cost_micros >= 0),
    cost_basis TEXT NULL
        CHECK (cost_basis IS NULL OR cost_basis IN ('estimated', 'measured_usage')),
    evidence_ref TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, request_key, revision),
    FOREIGN KEY (experiment_id, request_key)
        REFERENCES llm_spend_reservations(experiment_id, request_key),
    -- Unknown cost and unknown basis travel together: an amount without a
    -- basis is an assertion nobody can qualify, and a basis without an amount
    -- describes nothing.
    CHECK ((cost_micros IS NULL) = (cost_basis IS NULL)),
    -- A completion or a failure claim must name the evidence that established
    -- it. The grammar is checked in the repository; the table refuses the empty
    -- case even if a future caller bypasses it.
    CHECK (outcome NOT IN ('settled', 'failed') OR length(evidence_ref) > 0)
);

CREATE INDEX idx_llm_spend_settlements_outcome
    ON llm_spend_settlements(experiment_id, outcome);

CREATE TRIGGER llm_spend_settlements_append_only_update
BEFORE UPDATE ON llm_spend_settlements
BEGIN
    SELECT RAISE(ABORT, 'llm_spend_settlements is append-only');
END;

CREATE TRIGGER llm_spend_settlements_append_only_delete
BEFORE DELETE ON llm_spend_settlements
BEGIN
    SELECT RAISE(ABORT, 'llm_spend_settlements is append-only');
END;

CREATE TABLE llm_spend_settlement_epoch (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    audited_from_reservation_id INTEGER NOT NULL CHECK (audited_from_reservation_id >= 0),
    created_at TEXT NOT NULL
);

INSERT INTO llm_spend_settlement_epoch(
    singleton, audited_from_reservation_id, created_at
)
SELECT
    1,
    COALESCE(MAX(reservation_id), 0),
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
FROM llm_spend_reservations;
"""
