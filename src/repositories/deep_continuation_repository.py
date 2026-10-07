"""Deep-3: finalize the parent Deep terminal from a terminal Deep child.

Deep-3 projects a child's runtime terminal into the parent's control plane. The projection is
small on purpose - status, stop reason, provider status, a couple of digests - because the
evidence itself stays in the child's durable storage. A parent snapshot is a control plane, not
a second evidence store.

Everything is re-verified inside one transaction. The service already validated at admission,
but a child terminal can be reached long after that, so the transaction re-reads the parent, the
terminal, the handoff, the child, the execution envelope and the seed, and fails closed if any
of them changed in between. The first terminal wins: a completed or blocked parent terminal is
never rewritten.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.research.deep_handoff import (
    DEEP_TERMINAL_SCHEMA,
    load_deep_handoff,
)
from src.web.research.deep_runtime import (
    bind_execution_envelope,
    read_execution_envelope,
    read_seed,
    verify_seed_projection,
    verify_seed_sources,
)
from src.web.research.deep_seed import seed_refs_match

RESULT_SCHEMA = "deep-auto-continuation-v1"
TERMINAL_CHILD_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})

# Bounded blocked reasons. Raw exception text never reaches durable storage.
REASON_PARENT_UNAVAILABLE = "parent_unavailable"
REASON_TERMINAL_INTEGRITY = "terminal_integrity_failure"
REASON_HANDOFF_INTEGRITY = "handoff_integrity_failure"
REASON_CHILD_MISSING = "child_missing"
REASON_LINEAGE_MISMATCH = "lineage_mismatch"
REASON_SEED_INTEGRITY = "seed_integrity_failure"
REASON_ENVELOPE_INVALID = "execution_envelope_invalid"


class DeepFinalizationError(ValueError):
    """A deterministic integrity failure. Carries a bounded reason, never raw text."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DeepTerminalRead:
    present: bool
    terminal: Any


def child_terminal_projection(child: Any) -> dict[str, Any]:
    """The only child fields that may cross into the parent control plane."""

    return {
        "child_run_id": str(getattr(child, "id", "") or ""),
        "child_status": str(getattr(child, "status", "") or ""),
        "provider_status": str(getattr(child, "provider_status", "") or ""),
        "stop_reason": str(getattr(child, "stop_reason", "") or ""),
        "answer_confidence": str(getattr(child, "answer_confidence", "") or ""),
        "completed_at": str(getattr(child, "completed_at", "") or ""),
    }


def child_terminal_digest(child: Any) -> str:
    payload = child_terminal_projection(child)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


class DeepContinuationRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def read_terminal(self, parent_turn_id: str, thread_id: str) -> DeepTerminalRead:
        """Existence-aware read: a recorded null is present, not absent."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT rag_snapshot, thread_id FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
        if row is None or row["thread_id"] != thread_id:
            return DeepTerminalRead(False, None)
        snapshot = json.loads(row["rag_snapshot"]) or {}
        if "deep_terminal" not in snapshot:
            return DeepTerminalRead(False, None)
        return DeepTerminalRead(True, snapshot["deep_terminal"])

    def _validate_locked(
        self,
        connection: Any,
        *,
        parent_turn_id: str,
        thread_id: str,
        require_terminal_child: bool = True,
    ) -> tuple[dict, dict, Any]:
        """Re-verify the whole authority chain inside the open transaction."""

        parent_row = connection.execute(
            "SELECT * FROM chat_turns WHERE id = ?", (parent_turn_id,)
        ).fetchone()
        if (
            parent_row is None
            or parent_row["thread_id"] != thread_id
            or parent_row["status"] != "completed"
        ):
            raise DeepFinalizationError(REASON_PARENT_UNAVAILABLE)
        snapshot = json.loads(parent_row["rag_snapshot"]) or {}
        terminal = snapshot.get("deep_terminal")
        if not isinstance(terminal, dict):
            raise DeepFinalizationError(REASON_TERMINAL_INTEGRITY)
        if (
            terminal.get("schema_version") != DEEP_TERMINAL_SCHEMA
            or terminal.get("state") != "ESCALATE_DEEP"
        ):
            raise DeepFinalizationError(REASON_TERMINAL_INTEGRITY)
        owner = terminal.get("owner") or {}
        if owner.get("thread_id") != thread_id or owner.get("turn_id") != parent_turn_id:
            raise DeepFinalizationError(REASON_TERMINAL_INTEGRITY)

        raw_handoff = terminal.get("handoff")
        if not isinstance(raw_handoff, Mapping):
            raise DeepFinalizationError(REASON_HANDOFF_INTEGRITY)
        raw_handoff = dict(raw_handoff)
        handoff_sha256 = str(raw_handoff.get("payload_sha256") or "")
        if not handoff_sha256:
            raise DeepFinalizationError(REASON_HANDOFF_INTEGRITY)
        try:
            handoff = load_deep_handoff(raw_handoff)
        except ValueError as exc:
            raise DeepFinalizationError(REASON_HANDOFF_INTEGRITY) from exc
        if (
            str(handoff.get("parent_turn_id") or "") != parent_turn_id
            or str(handoff.get("query") or "") != str(parent_row["user_message"] or "")
        ):
            raise DeepFinalizationError(REASON_HANDOFF_INTEGRITY)

        child_run_id = str(terminal.get("child_run_id") or "")
        if not child_run_id:
            raise DeepFinalizationError(REASON_CHILD_MISSING)
        child_row = connection.execute(
            "SELECT * FROM web_lookup_runs WHERE id = ?", (child_run_id,)
        ).fetchone()
        if child_row is None:
            raise DeepFinalizationError(REASON_CHILD_MISSING)
        if (
            str(child_row["owner_thread_id"] or "") != thread_id
            or str(child_row["parent_run_id"] or "")
            != str(handoff.get("standard_child_run_id") or "")
            or str(child_row["query"] or "") != str(handoff.get("query") or "")
        ):
            raise DeepFinalizationError(REASON_LINEAGE_MISMATCH)
        child_status = str(child_row["status"] or "")
        if require_terminal_child and child_status not in TERMINAL_CHILD_STATUSES:
            # Only finalization needs a terminal child. Blocking records an admission failure,
            # which can happen while the child is still pending or running.
            raise DeepFinalizationError(REASON_LINEAGE_MISMATCH)

        child_context = json.loads(child_row["research_context"] or "{}") or {}
        present, envelope = read_execution_envelope(child_context)
        if not present:
            raise DeepFinalizationError(REASON_ENVELOPE_INVALID)
        valid, _why = bind_execution_envelope(
            envelope, parent_turn_id=parent_turn_id, handoff_sha256=handoff_sha256
        )
        if not valid:
            raise DeepFinalizationError(REASON_ENVELOPE_INVALID)

        seed_present, seed_value = read_seed(child_context)
        if not seed_present:
            raise DeepFinalizationError(REASON_SEED_INTEGRITY)
        for check in (verify_seed_sources, verify_seed_projection):
            ok, _reason = check(seed_value)
            if not ok:
                raise DeepFinalizationError(REASON_SEED_INTEGRITY)
        if not seed_refs_match(
            list(handoff.get("seed_source_refs") or []), list(seed_value.get("refs") or [])
        ):
            raise DeepFinalizationError(REASON_SEED_INTEGRITY)

        return snapshot, terminal, child_row

    def _write(
        self,
        connection: Any,
        *,
        parent_turn_id: str,
        snapshot: dict,
        terminal: dict,
    ) -> None:
        connection.execute(
            "UPDATE chat_turns SET rag_snapshot = ?, updated_at = ? WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), utc_now(), parent_turn_id),
        )

    def finalize(
        self,
        *,
        parent_turn_id: str,
        thread_id: str,
        expected_child_run_id: str,
    ) -> dict:
        """pending -> completed, in one transaction. First terminal wins."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot, terminal, child_row = self._validate_locked(
                connection, parent_turn_id=parent_turn_id, thread_id=thread_id
            )
            if str(terminal.get("dispatch_status") or "") in {"completed", "blocked"}:
                return dict(terminal)
            if str(terminal.get("child_run_id") or "") != str(expected_child_run_id):
                raise DeepFinalizationError(REASON_CHILD_MISSING)

            projection = child_terminal_projection(
                _ChildView(child_row, str(child_row["status"] or ""))
            )
            result = {
                "schema_version": RESULT_SCHEMA,
                "child_run_id": projection["child_run_id"],
                "child_status": projection["child_status"],
                "provider_status": projection["provider_status"],
                "stop_reason": projection["stop_reason"],
                "answer_confidence": projection["answer_confidence"],
                "completed_at": projection["completed_at"],
                "handoff_sha256": str((terminal.get("handoff") or {}).get("payload_sha256") or ""),
                "child_terminal_sha256": child_terminal_digest(
                    _ChildView(child_row, str(child_row["status"] or ""))
                ),
                "publication_authority": False,
            }
            terminal = dict(terminal)
            terminal["dispatch_status"] = "completed"
            terminal["result"] = result
            snapshot = dict(snapshot)
            snapshot["deep_terminal"] = terminal
            self._write(
                connection,
                parent_turn_id=parent_turn_id,
                snapshot=snapshot,
                terminal=terminal,
            )
        return terminal

    def block(
        self,
        *,
        parent_turn_id: str,
        thread_id: str,
        reason: str,
    ) -> dict:
        """pending -> blocked, in one transaction. Only a bounded reason is recorded."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot, terminal, _child = self._validate_locked(
                connection,
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                require_terminal_child=False,
            )
            if str(terminal.get("dispatch_status") or "") in {"completed", "blocked"}:
                return dict(terminal)
            terminal = dict(terminal)
            terminal["dispatch_status"] = "blocked"
            terminal["reason"] = str(reason)
            snapshot = dict(snapshot)
            snapshot["deep_terminal"] = terminal
            self._write(
                connection,
                parent_turn_id=parent_turn_id,
                snapshot=snapshot,
                terminal=terminal,
            )
        return terminal


@dataclass(frozen=True)
class _ChildView:
    """Adapts a raw row to the attribute names the projection uses."""

    row: Any
    status: str

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def provider_status(self) -> str:
        return str(self.row["provider_status"] or "")

    @property
    def stop_reason(self) -> str:
        return str(self.row["stop_reason"] or "")

    @property
    def answer_confidence(self) -> str:
        return str(self.row["answer_confidence"] or "")

    @property
    def completed_at(self) -> str:
        return str(self.row["completed_at"] or "")
