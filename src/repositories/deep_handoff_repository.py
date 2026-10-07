"""Deep-1: durable parent Deep terminal on existing chat-turn storage.

Deep owns its own namespace. It never reopens ``lookup_terminal`` or ``standard_continuation``:
Standard's artifact is closed and this layer only reads it.

The write is atomic and additive. Everything else in the parent snapshot must survive
bit-for-bit, so this is a single transaction that loads the snapshot, re-verifies the Standard
authority it depends on, and writes only ``deep_terminal``.
"""

from __future__ import annotations

import json
from typing import Any

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.research.deep_handoff import CONTINUATION_SCHEMA, DEEP_TERMINAL_SCHEMA


class DeepHandoffRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def read_terminal(self, parent_turn_id: str, thread_id: str) -> dict | None:
        """The saved Deep terminal, if this parent already has one. Owner-checked."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT rag_snapshot, thread_id FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
        if row is None or row["thread_id"] != thread_id:
            return None
        terminal = (json.loads(row["rag_snapshot"]) or {}).get("deep_terminal")
        if isinstance(terminal, dict) and terminal.get("schema_version") == DEEP_TERMINAL_SCHEMA:
            return terminal
        return None

    def persist(self, *, parent_turn_id: str, thread_id: str, terminal: dict) -> dict:
        """Add ``deep_terminal`` in one transaction, preserving every other snapshot key."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT rag_snapshot, thread_id, status FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
            if row is None or row["thread_id"] != thread_id:
                raise ValueError("Deep parent unavailable")
            if row["status"] != "completed":
                raise ValueError("Deep parent is not completed")
            snapshot = json.loads(row["rag_snapshot"])

            existing = snapshot.get("deep_terminal")
            if isinstance(existing, dict) and existing.get("schema_version") == DEEP_TERMINAL_SCHEMA:
                # Idempotent: the first terminal wins, a retry does not rewrite it.
                return existing

            lookup_terminal = snapshot.get("lookup_terminal") or {}
            if (
                lookup_terminal.get("state") != "ESCALATE_STANDARD"
                or lookup_terminal.get("dispatch_status") != "completed"
            ):
                raise ValueError("no completed Standard terminal to escalate from")
            continuation = snapshot.get("standard_continuation") or {}
            if (
                continuation.get("schema_version") != CONTINUATION_SCHEMA
                or continuation.get("publication_authority") is not False
            ):
                raise ValueError("Standard continuation artifact is not valid")

            snapshot["deep_terminal"] = terminal
            connection.execute(
                "UPDATE chat_turns SET rag_snapshot = ? WHERE id = ?",
                (json.dumps(snapshot, ensure_ascii=False), parent_turn_id),
            )
        return terminal

    def snapshot_keys(self, parent_turn_id: str, thread_id: str) -> dict[str, Any]:
        """The raw parent snapshot, for tests that assert what was and was not written."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT rag_snapshot, thread_id FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
        if row is None or row["thread_id"] != thread_id:
            raise ValueError("Deep parent unavailable")
        return json.loads(row["rag_snapshot"])
