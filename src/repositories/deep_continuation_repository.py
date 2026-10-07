"""Deep-3: finalize the parent Deep terminal from a terminal Deep child.

Deep-3 projects a child's runtime terminal into the parent's control plane. The projection is
small on purpose - status, stop reason, provider status, a couple of digests - because the
evidence itself stays in the child's durable storage. A parent snapshot is a control plane, not
a second evidence store.

Validation is layered, and the layering is the point.

* **Control plane** (parent, terminal top level, owner) is read inside the transaction and is
  required by every transition.
* **Positive validation** (handoff, child, execution envelope, seed) is required only to write a
  *successful* terminal. Blocking records that something is wrong, so it must not require the
  very component that was found broken to validate cleanly - otherwise the corruption that
  caused the block would also prevent the block from being persisted.
* **First terminal wins** is decided immediately after the control-plane read, before any
  positive validation, so a completed parent is never re-examined against a child that has since
  been damaged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.research.deep_handoff import DEEP_TERMINAL_SCHEMA, load_deep_handoff
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
TERMINAL_DISPATCH_STATUSES = frozenset({"completed", "blocked"})

# Bounded blocked reasons. Raw exception text never reaches durable storage.
REASON_PARENT_UNAVAILABLE = "parent_unavailable"
REASON_TERMINAL_INTEGRITY = "terminal_integrity_failure"
REASON_HANDOFF_INTEGRITY = "handoff_integrity_failure"
REASON_CHILD_MISSING = "child_missing"
REASON_LINEAGE_MISMATCH = "lineage_mismatch"
REASON_SEED_INTEGRITY = "seed_integrity_failure"
REASON_ENVELOPE_INVALID = "execution_envelope_invalid"
REASON_CLAIM_ENGINE_UNUSABLE = "claim_engine_unusable"
REASON_EXECUTION_STATE_MISMATCH = "execution_state_mismatch"
REASON_ADMISSION_FAILED = "admission_failed"

BLOCKED_REASONS = frozenset(
    {
        REASON_PARENT_UNAVAILABLE,
        REASON_TERMINAL_INTEGRITY,
        REASON_HANDOFF_INTEGRITY,
        REASON_CHILD_MISSING,
        REASON_LINEAGE_MISMATCH,
        REASON_SEED_INTEGRITY,
        REASON_ENVELOPE_INVALID,
        REASON_CLAIM_ENGINE_UNUSABLE,
        REASON_EXECUTION_STATE_MISMATCH,
        REASON_ADMISSION_FAILED,
    }
)


class DeepFinalizationError(ValueError):
    """A deterministic integrity failure. Carries a bounded reason, never raw text."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DeepTerminalRead:
    present: bool
    terminal: Any


def bounded_reason(reason: str) -> str:
    value = str(reason or "")
    return value if value in BLOCKED_REASONS else REASON_ADMISSION_FAILED


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


def validate_recorded_terminal(terminal: Any) -> tuple[bool, str]:
    """A read-only check of an already-recorded terminal. Never rewrites anything.

    First-terminal-wins does not mean a recorded terminal is trusted: a completed terminal
    without a valid result, or with publication authority, is not a terminal we can report as
    settled.
    """

    if not isinstance(terminal, dict):
        return (False, REASON_TERMINAL_INTEGRITY)
    if (
        terminal.get("schema_version") != DEEP_TERMINAL_SCHEMA
        or terminal.get("state") != "ESCALATE_DEEP"
    ):
        return (False, REASON_TERMINAL_INTEGRITY)
    owner = terminal.get("owner")
    if not isinstance(owner, Mapping) or not owner.get("thread_id") or not owner.get("turn_id"):
        return (False, REASON_TERMINAL_INTEGRITY)
    status = str(terminal.get("dispatch_status") or "")
    if status == "completed":
        result = terminal.get("result")
        if not isinstance(result, Mapping):
            return (False, REASON_TERMINAL_INTEGRITY)
        if result.get("schema_version") != RESULT_SCHEMA:
            return (False, REASON_TERMINAL_INTEGRITY)
        if result.get("publication_authority") is not False:
            return (False, REASON_TERMINAL_INTEGRITY)
        if str(result.get("child_run_id") or "") != str(terminal.get("child_run_id") or ""):
            return (False, REASON_TERMINAL_INTEGRITY)
        if str(result.get("child_status") or "") not in TERMINAL_CHILD_STATUSES:
            return (False, REASON_TERMINAL_INTEGRITY)
        handoff = terminal.get("handoff")
        recorded = str((handoff or {}).get("payload_sha256") or "") if isinstance(handoff, Mapping) else ""
        if not recorded or str(result.get("handoff_sha256") or "") != recorded:
            return (False, REASON_TERMINAL_INTEGRITY)
        return (True, "")
    if status == "blocked":
        if str(terminal.get("reason") or "") not in BLOCKED_REASONS:
            return (False, REASON_TERMINAL_INTEGRITY)
        return (True, "")
    if status == "pending":
        return (True, "")
    return (False, REASON_TERMINAL_INTEGRITY)


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

    # --- control plane ---------------------------------------------------------------

    def _read_control_locked(
        self, connection: Any, *, parent_turn_id: str, thread_id: str
    ) -> tuple[dict, dict, Any]:
        """Parent + terminal top level. Required by every transition."""

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
        return snapshot, terminal, parent_row

    # --- positive validation ---------------------------------------------------------

    def _positive_validate_locked(
        self,
        connection: Any,
        *,
        parent_turn_id: str,
        thread_id: str,
        parent_row: Any,
        terminal: dict,
    ) -> Any:
        """Everything that must still hold to write a *successful* terminal."""

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
        if str(child_row["status"] or "") not in TERMINAL_CHILD_STATUSES:
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
        return child_row

    # --- transitions -----------------------------------------------------------------

    def _write(self, connection: Any, *, parent_turn_id: str, snapshot: dict) -> None:
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
            snapshot, terminal, parent_row = self._read_control_locked(
                connection, parent_turn_id=parent_turn_id, thread_id=thread_id
            )
            # First terminal wins, before any positive validation: a settled parent must never
            # be re-examined against a child that has since been damaged.
            if str(terminal.get("dispatch_status") or "") in TERMINAL_DISPATCH_STATUSES:
                return dict(terminal)
            if str(terminal.get("dispatch_status") or "") != "pending":
                raise DeepFinalizationError(REASON_TERMINAL_INTEGRITY)
            if str(terminal.get("child_run_id") or "") != str(expected_child_run_id):
                raise DeepFinalizationError(REASON_CHILD_MISSING)
            child_row = self._positive_validate_locked(
                connection,
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                parent_row=parent_row,
                terminal=terminal,
            )

            view = _ChildView(child_row)
            result = {
                "schema_version": RESULT_SCHEMA,
                "child_run_id": view.id,
                "child_status": view.status,
                "provider_status": view.provider_status,
                "stop_reason": view.stop_reason,
                "answer_confidence": view.answer_confidence,
                "completed_at": view.completed_at,
                "handoff_sha256": str((terminal.get("handoff") or {}).get("payload_sha256") or ""),
                "child_terminal_sha256": child_terminal_digest(view),
                "publication_authority": False,
            }
            terminal = dict(terminal)
            terminal["dispatch_status"] = "completed"
            terminal["result"] = result
            snapshot = dict(snapshot)
            snapshot["deep_terminal"] = terminal
            self._write(connection, parent_turn_id=parent_turn_id, snapshot=snapshot)
        return terminal

    def block(
        self,
        *,
        parent_turn_id: str,
        thread_id: str,
        reason: str,
    ) -> dict:
        """pending -> blocked, in one transaction.

        Deliberately does not run positive validation: the component that failed is exactly what
        caused this block, and requiring it to validate cleanly would prevent the block from
        ever being recorded.
        """

        bounded = bounded_reason(reason)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot, terminal, _parent_row = self._read_control_locked(
                connection, parent_turn_id=parent_turn_id, thread_id=thread_id
            )
            if str(terminal.get("dispatch_status") or "") in TERMINAL_DISPATCH_STATUSES:
                return dict(terminal)
            if str(terminal.get("dispatch_status") or "") != "pending":
                raise DeepFinalizationError(REASON_TERMINAL_INTEGRITY)
            terminal = dict(terminal)
            terminal["dispatch_status"] = "blocked"
            terminal["reason"] = bounded
            snapshot = dict(snapshot)
            snapshot["deep_terminal"] = terminal
            self._write(connection, parent_turn_id=parent_turn_id, snapshot=snapshot)
        return terminal


@dataclass(frozen=True)
class _ChildView:
    """Adapts a raw row to the attribute names the projection uses."""

    row: Any

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def status(self) -> str:
        return str(self.row["status"] or "")

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
