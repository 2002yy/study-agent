"""Runtime schema migration for saved interactive-UI state snapshots.

A snapshot is what the learner had done inside one generated document, not the
document itself and not a log of how they got there. The host owns it so the
generated code never touches storage, and the component id + revision let a
restore refuse state that belongs to a different version.
"""

from __future__ import annotations

INTERACTIVE_STATE_MIGRATION_V31 = """
CREATE TABLE interactive_state_snapshots (
    thread_id TEXT NOT NULL REFERENCES chat_threads(id),
    component_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 999),
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (thread_id, component_id, revision)
);
"""
