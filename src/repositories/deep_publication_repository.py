"""Deep-4A: the durable publication-candidate terminal on the parent control plane.

This repository owns one parent key, ``rag_snapshot.deep_publication``, and nothing else. It
records that a Deep child's research reached an audited candidate - never that anything was
published.

Validation is layered the same way Deep-3's is, and for the same reason.

* **Control plane** (parent, publication top level, owner) is required by every transition.
* **Positive validation** (Deep terminal, child lineage, source-run digest) is required only to
  write a *successful* terminal. Blocking records that something is wrong, so it must not
  require the component that was found broken to validate cleanly.
* **First terminal wins** is decided immediately after the control-plane read, before positive
  validation, so a settled audit is never reinterpreted because the child was later corrupted.

Two digests close the window between validating the child and committing the audit: the Deep
terminal digest and the source-run digest. A change in either blocks rather than silently
auditing a different child than the one that was validated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.web.research.deep_handoff import load_deep_handoff
from src.repositories.deep_continuation_repository import (
    REASON_PARENT_UNAVAILABLE,
    _ChildView,
    child_terminal_digest,
    TERMINAL_CHILD_STATUSES,
    DeepFinalizationError,
    validate_recorded_terminal,
)

PUBLICATION_SCHEMA = "deep-publication-v1"
AUDIT_RESULT_SCHEMA = "deep-audit-artifact-v1"

PENDING = "pending"
AUDITED = "audited"
BLOCKED = "blocked"
TERMINAL_STATUSES = frozenset({AUDITED, BLOCKED})

REASON_PUBLICATION_INTEGRITY = "publication_integrity_failure"
REASON_DEEP_TERMINAL_INTEGRITY = "deep_terminal_integrity_failure"
REASON_CHILD_MISSING = "child_missing"
REASON_LINEAGE_MISMATCH = "lineage_mismatch"
REASON_SOURCE_RUN_CHANGED = "source_run_changed"
REASON_CLAIM_ENGINE_UNUSABLE = "claim_engine_unusable"

BLOCKED_REASONS = frozenset(
    {
        REASON_PARENT_UNAVAILABLE,
        REASON_PUBLICATION_INTEGRITY,
        REASON_DEEP_TERMINAL_INTEGRITY,
        REASON_CHILD_MISSING,
        REASON_LINEAGE_MISMATCH,
        REASON_SOURCE_RUN_CHANGED,
        REASON_CLAIM_ENGINE_UNUSABLE,
    }
)

AUDIT_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "child_run_id",
        "child_status",
        "deep_terminal_sha256",
        "child_terminal_sha256",
        "source_run_sha256",
        "research_state_sha256",
        "projection_sha256",
        "draft_sha256",
        "audit_sha256",
        "candidate_status",
        "audit_verdict",
        "approval_status",
        "question_coverage",
        "evidence_grounding",
        "issue_codes",
        "judge_authority",
        "publication_authority",
        "audited_at",
    }
)

CANDIDATE_STATUSES = frozenset({"assembled", "mechanically_rejected"})
APPROVAL_STATUS = "audited-but-not-approved"

# The source-run projection: durable facts only, never transient in-memory values.
SOURCE_RUN_KEYS = (
    "id",
    "owner_thread_id",
    "parent_run_id",
    "query",
    "status",
    "provider_status",
    "stop_reason",
    "answer_confidence",
    "completed_at",
    "selected_sources",
    "rejected_sources",
    "research_context",
)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def deep_terminal_digest(terminal: Mapping[str, Any]) -> str:
    return canonical_digest(dict(terminal))


def source_run_digest(row: Any) -> str:
    """Digest of the durable Deep child used for the audit."""

    payload: dict[str, Any] = {}
    for key in SOURCE_RUN_KEYS:
        try:
            value = row[key]
        except (KeyError, IndexError):
            value = None
        if key in {"selected_sources", "rejected_sources", "research_context"}:
            try:
                payload[key] = json.loads(value or "{}") if isinstance(value, str) else value
            except ValueError:
                payload[key] = value
        else:
            payload[key] = value
    return canonical_digest(payload)


def current_child_terminal_digest(child_row: Any) -> str:
    """The Deep-3 child terminal projection, recomputed from the current child row.

    This is the same projection Deep-3 recorded, so comparing it against the terminal proves
    the child is still the one that was finalized rather than merely reading the digest back
    out of the terminal.
    """

    return child_terminal_digest(_ChildView(child_row))


def _terminal_lineage(terminal: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """(child_run_id, standard_child_run_id, query, child_terminal_sha256) from the terminal."""

    child_run_id = str(terminal.get("child_run_id") or "")
    handoff_raw = terminal.get("handoff")
    standard_child_run_id = query = ""
    if isinstance(handoff_raw, Mapping):
        try:
            handoff = load_deep_handoff(dict(handoff_raw))
        except ValueError:
            handoff = {}
        standard_child_run_id = str(handoff.get("standard_child_run_id") or "")
        query = str(handoff.get("query") or "")
    result = terminal.get("result")
    child_terminal_sha256 = (
        str(result.get("child_terminal_sha256") or "") if isinstance(result, Mapping) else ""
    )
    return (child_run_id, standard_child_run_id, query, child_terminal_sha256)


def _lineage_matches(child_row: Any, terminal: Mapping[str, Any]) -> bool:
    """The child must be the one the Deep terminal names, by identity and lineage."""

    child_run_id, standard_child_run_id, query, _digest = _terminal_lineage(terminal)
    # Exact, unconditional comparison: the terminal is the authority, so a missing expectation
    # is a mismatch, not a reason to skip the check.
    if str(child_row["id"]) != child_run_id:
        return False
    if str(child_row["parent_run_id"] or "") != standard_child_run_id:
        return False
    if str(child_row["query"] or "") != query:
        return False
    return True


def bounded_reason(reason: str) -> str:
    value = str(reason or "")
    return value if value in BLOCKED_REASONS else REASON_PUBLICATION_INTEGRITY


@dataclass(frozen=True)
class DeepPublicationRead:
    present: bool
    publication: Any


def validate_recorded_publication(
    publication: Any,
    *,
    parent_turn_id: str,
    thread_id: str,
) -> tuple[bool, str]:
    """Read-only check of an already-recorded publication terminal. Never rewrites.

    A recorded ``audited`` is not trusted merely because it exists: the result must be exactly
    the bounded audit artifact, with no publication authority. A recorded ``blocked`` needs only
    a bounded reason and no result - the corruption that caused it is not re-required to be
    valid.
    """

    if not isinstance(publication, dict):
        return (False, REASON_PUBLICATION_INTEGRITY)
    if publication.get("schema_version") != PUBLICATION_SCHEMA:
        return (False, REASON_PUBLICATION_INTEGRITY)
    if publication.get("publication_authority") is not False:
        return (False, REASON_PUBLICATION_INTEGRITY)
    status = str(publication.get("dispatch_status") or "")
    if status == BLOCKED:
        # Blocking records that an authority component is already broken, so a blocked terminal
        # is not required to prove its owner or source still validates.
        if str(publication.get("reason") or "") not in BLOCKED_REASONS:
            return (False, REASON_PUBLICATION_INTEGRITY)
        if publication.get("result") is not None:
            return (False, REASON_PUBLICATION_INTEGRITY)
        return (True, "")

    owner = publication.get("owner")
    if (
        not isinstance(owner, Mapping)
        or str(owner.get("thread_id") or "") != thread_id
        or str(owner.get("turn_id") or "") != parent_turn_id
    ):
        return (False, REASON_PUBLICATION_INTEGRITY)
    if status == PENDING:
        return (True, "")
    if status == AUDITED:
        result = publication.get("result")
        if not isinstance(result, Mapping) or set(result) != AUDIT_RESULT_KEYS:
            return (False, REASON_PUBLICATION_INTEGRITY)
        if result.get("schema_version") != AUDIT_RESULT_SCHEMA:
            return (False, REASON_PUBLICATION_INTEGRITY)
        if result.get("publication_authority") is not False:
            return (False, REASON_PUBLICATION_INTEGRITY)
        if result.get("judge_authority") != "none":
            return (False, REASON_PUBLICATION_INTEGRITY)
        if result.get("approval_status") != APPROVAL_STATUS:
            return (False, REASON_PUBLICATION_INTEGRITY)
        if str(result.get("candidate_status") or "") not in CANDIDATE_STATUSES:
            return (False, REASON_PUBLICATION_INTEGRITY)
        for key in (
            "deep_terminal_sha256",
            "child_terminal_sha256",
            "source_run_sha256",
            "research_state_sha256",
            "projection_sha256",
            "audit_sha256",
        ):
            digest = str(result.get(key) or "")
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                return (False, REASON_PUBLICATION_INTEGRITY)
        # draft_sha256 is the one field the contract permits to be empty.
        draft = str(result.get("draft_sha256") or "")
        if draft and (
            len(draft) != 64 or any(c not in "0123456789abcdef" for c in draft)
        ):
            return (False, REASON_PUBLICATION_INTEGRITY)
        if str(owner.get("child_run_id") or "") != str(result.get("child_run_id") or ""):
            # The audit must describe the child the terminal owns.
            return (False, REASON_PUBLICATION_INTEGRITY)
        # The result and the recorded source must describe the same audit, so a locally edited
        # digest cannot pass merely by being well-formed.
        source = publication.get("source")
        if not isinstance(source, Mapping):
            return (False, REASON_PUBLICATION_INTEGRITY)
        for key in ("deep_terminal_sha256", "child_terminal_sha256", "source_run_sha256"):
            if str(result.get(key) or "") != str(source.get(key) or ""):
                return (False, REASON_PUBLICATION_INTEGRITY)
        return (True, "")
    return (False, REASON_PUBLICATION_INTEGRITY)


class DeepPublicationRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def read(self, parent_turn_id: str, thread_id: str) -> DeepPublicationRead:
        """Existence-aware read: a recorded null is present, not absent."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT rag_snapshot, thread_id FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
        if row is None or row["thread_id"] != thread_id:
            return DeepPublicationRead(False, None)
        snapshot = json.loads(row["rag_snapshot"]) or {}
        if "deep_publication" not in snapshot:
            return DeepPublicationRead(False, None)
        return DeepPublicationRead(True, snapshot["deep_publication"])

    def _read_control_locked(
        self,
        connection: Any,
        *,
        parent_turn_id: str,
        thread_id: str,
        require_owner: bool = True,
    ) -> tuple[dict, dict, Any]:
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
        publication = snapshot.get("deep_publication")
        if not isinstance(publication, dict):
            raise DeepFinalizationError(REASON_PUBLICATION_INTEGRITY)
        if publication.get("schema_version") != PUBLICATION_SCHEMA:
            raise DeepFinalizationError(REASON_PUBLICATION_INTEGRITY)
        if require_owner:
            owner = publication.get("owner") or {}
            if owner.get("thread_id") != thread_id or owner.get("turn_id") != parent_turn_id:
                raise DeepFinalizationError(REASON_PUBLICATION_INTEGRITY)
        return snapshot, publication, parent_row

    def _validate_source_locked(
        self,
        connection: Any,
        *,
        parent_turn_id: str,
        thread_id: str,
        publication: dict,
        audit_source_digest: str,
    ) -> Any:
        """Everything that must still hold to write a *successful* audit terminal."""

        snapshot = json.loads(
            connection.execute(
                "SELECT rag_snapshot FROM chat_turns WHERE id = ?", (parent_turn_id,)
            ).fetchone()["rag_snapshot"]
        ) or {}
        terminal = snapshot.get("deep_terminal")
        valid, reason = validate_recorded_terminal(
            terminal, parent_turn_id=parent_turn_id, thread_id=thread_id
        )
        if (
            not valid
            or not isinstance(terminal, dict)
            or str(terminal.get("dispatch_status") or "") != "completed"
        ):
            raise DeepFinalizationError(REASON_DEEP_TERMINAL_INTEGRITY)
        source = publication.get("source") or {}
        if deep_terminal_digest(terminal) != str(source.get("deep_terminal_sha256") or ""):
            raise DeepFinalizationError(REASON_DEEP_TERMINAL_INTEGRITY)
        child_run_id = str((publication.get("owner") or {}).get("child_run_id") or "")
        if not child_run_id:
            raise DeepFinalizationError(REASON_CHILD_MISSING)
        child_row = connection.execute(
            "SELECT * FROM web_lookup_runs WHERE id = ?", (child_run_id,)
        ).fetchone()
        if child_row is None:
            raise DeepFinalizationError(REASON_CHILD_MISSING)
        if (
            str(child_row["owner_thread_id"] or "") != thread_id
            or str(child_row["status"] or "") not in TERMINAL_CHILD_STATUSES
            or not _lineage_matches(child_row, terminal)
        ):
            raise DeepFinalizationError(REASON_LINEAGE_MISMATCH)

        current = source_run_digest(child_row)
        # The digest recorded when the candidate was attached is the authority: a child that
        # changed since then must not be audited under the old candidate's provenance.
        if current != str(source.get("source_run_sha256") or ""):
            raise DeepFinalizationError(REASON_SOURCE_RUN_CHANGED)
        # And the auditor's own snapshot must be that same child.
        if current != str(audit_source_digest):
            raise DeepFinalizationError(REASON_SOURCE_RUN_CHANGED)

        recorded_child_digest = str(source.get("child_terminal_sha256") or "")
        if (
            not recorded_child_digest
            or current_child_terminal_digest(child_row) != recorded_child_digest
            or recorded_child_digest != _terminal_lineage(terminal)[3]
        ):
            # The child terminal changed, or is not the one the terminal named.
            raise DeepFinalizationError(REASON_DEEP_TERMINAL_INTEGRITY)
        return child_row

    def _write(self, connection: Any, *, parent_turn_id: str, snapshot: dict) -> None:
        connection.execute(
            "UPDATE chat_turns SET rag_snapshot = ?, updated_at = ? WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), utc_now(), parent_turn_id),
        )

    def attach_pending(
        self,
        *,
        parent_turn_id: str,
        thread_id: str,
        child_run_id: str,
    ) -> dict:
        """ABSENT -> pending, in one transaction."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            if "deep_publication" in snapshot:
                # Key existence, not truthiness: a recorded null is present-but-malformed, not
                # absent, and must never be silently replaced.
                existing = snapshot["deep_publication"]
                return dict(existing) if isinstance(existing, dict) else {}
            terminal = snapshot.get("deep_terminal")
            valid, reason = validate_recorded_terminal(
                terminal, parent_turn_id=parent_turn_id, thread_id=thread_id
            )
            if (
                not valid
                or not isinstance(terminal, dict)
                or str(terminal.get("dispatch_status") or "") != "completed"
            ):
                raise DeepFinalizationError(reason or REASON_DEEP_TERMINAL_INTEGRITY)

            child_row = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (child_run_id,)
            ).fetchone()
            if child_row is None:
                raise DeepFinalizationError(REASON_CHILD_MISSING)
            if (
                str(child_row["owner_thread_id"] or "") != thread_id
                or str(child_row["status"] or "") not in TERMINAL_CHILD_STATUSES
                or not _lineage_matches(child_row, terminal)
            ):
                raise DeepFinalizationError(REASON_LINEAGE_MISMATCH)

            recorded_child_digest = _terminal_lineage(terminal)[3]
            if (
                not recorded_child_digest
                or current_child_terminal_digest(child_row) != recorded_child_digest
            ):
                # The child is not the one Deep-3 finalized.
                raise DeepFinalizationError(REASON_DEEP_TERMINAL_INTEGRITY)
            publication = {
                "schema_version": PUBLICATION_SCHEMA,
                "dispatch_status": PENDING,
                "owner": {
                    "thread_id": thread_id,
                    "turn_id": parent_turn_id,
                    "child_run_id": child_run_id,
                },
                "source": {
                    "deep_terminal_sha256": deep_terminal_digest(terminal),
                    "child_terminal_sha256": recorded_child_digest,
                    "source_run_sha256": source_run_digest(child_row),
                },
                "publication_authority": False,
            }
            snapshot = dict(snapshot)
            snapshot["deep_publication"] = publication
            self._write(connection, parent_turn_id=parent_turn_id, snapshot=snapshot)
        return publication

    def finalize_audited(
        self,
        *,
        parent_turn_id: str,
        thread_id: str,
        audit_source_digest: str,
        result: dict,
    ) -> dict:
        """pending -> audited, in one transaction. First terminal wins.

        The audit is bound to the child twice: the current child must equal the digest recorded
        when the candidate was attached (so a child that changed after attach cannot be audited)
        and the digest the auditor actually used (so the projection and the provenance cannot
        describe different snapshots).
        """

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            snapshot, publication, _parent_row = self._read_control_locked(
                connection, parent_turn_id=parent_turn_id, thread_id=thread_id
            )
            # First terminal wins, before positive validation.
            if str(publication.get("dispatch_status") or "") in TERMINAL_STATUSES:
                return dict(publication)
            if str(publication.get("dispatch_status") or "") != PENDING:
                raise DeepFinalizationError(REASON_PUBLICATION_INTEGRITY)
            self._validate_source_locked(
                connection,
                parent_turn_id=parent_turn_id,
                thread_id=thread_id,
                publication=publication,
                audit_source_digest=audit_source_digest,
            )
            publication = dict(publication)
            publication["dispatch_status"] = AUDITED
            publication["result"] = dict(result)
            publication["publication_authority"] = False
            snapshot = dict(snapshot)
            snapshot["deep_publication"] = publication
            self._write(connection, parent_turn_id=parent_turn_id, snapshot=snapshot)
        return publication

    def block(
        self,
        *,
        parent_turn_id: str,
        thread_id: str,
        reason: str,
    ) -> dict:
        """pending -> blocked, in one transaction.

        Deliberately skips positive validation: the component that failed is what caused this
        block, so requiring it to validate would prevent the block from ever being recorded.
        """

        bounded = bounded_reason(reason)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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

            if "deep_publication" in snapshot:
                existing = snapshot["deep_publication"]
                if not isinstance(existing, dict):
                    # Present-but-null or malformed is durable corruption: never treated as
                    # absent, never recreated, never repaired.
                    raise DeepFinalizationError(REASON_PUBLICATION_INTEGRITY)
                owner = existing.get("owner") or {}
                if (
                    owner.get("thread_id") != thread_id
                    or owner.get("turn_id") != parent_turn_id
                ):
                    bounded = REASON_PUBLICATION_INTEGRITY
                status = str(existing.get("dispatch_status") or "")
                if status in TERMINAL_STATUSES:
                    return dict(existing)
                if status != PENDING:
                    raise DeepFinalizationError(REASON_PUBLICATION_INTEGRITY)
                publication = dict(existing)
            else:
                # The failure happened before a candidate was attached (for example a lineage
                # mismatch at attach time). The block is still the honest durable record.
                terminal = snapshot.get("deep_terminal")
                child_run_id = ""
                if isinstance(terminal, dict):
                    child_run_id = _terminal_lineage(terminal)[0]
                publication = {
                    "schema_version": PUBLICATION_SCHEMA,
                    "owner": {
                        "thread_id": thread_id,
                        "turn_id": parent_turn_id,
                        "child_run_id": child_run_id,
                    },
                    "source": {},
                }

            publication["dispatch_status"] = BLOCKED
            publication["reason"] = bounded
            publication["publication_authority"] = False
            snapshot = dict(snapshot)
            snapshot["deep_publication"] = publication
            self._write(connection, parent_turn_id=parent_turn_id, snapshot=snapshot)
        return publication
