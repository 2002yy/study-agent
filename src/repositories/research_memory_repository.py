"""Append-only, thread-scoped transaction boundary for research leads."""

from __future__ import annotations

from datetime import date
import json

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import _from_row
from src.web.research.contracts import ResearchState
from src.web.research.persistent_memory import (
    RecallCandidate,
    ResearchMemoryRevision,
    known_research_evidence_ids,
    normalized_topic,
    revision_freshness,
    state_digest,
)


class ResearchMemoryRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()

    def cursor_version(self, owner_thread_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT version FROM research_memory_threads WHERE owner_thread_id = ?",
                (owner_thread_id,),
            ).fetchone()
        return int(row["version"]) if row else 0

    def publish(
        self, revision: ResearchMemoryRevision, *, expected_cursor_version: int
    ) -> ResearchMemoryRevision:
        """Idempotency, source check, append and cursor CAS share one transaction."""

        checked = ResearchMemoryRevision.from_dict(revision.to_dict())
        if any(claim.status == "confirmed" for claim in checked.claims):
            raise ValueError("confirmed memory publication is not qualified")
        if type(expected_cursor_version) is not int or expected_cursor_version < 0:
            raise ValueError("invalid memory cursor version")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?",
                (checked.source_run_id,),
            ).fetchone()
            if source is None or source["owner_thread_id"] != checked.owner_thread_id:
                raise ValueError("memory source owner mismatch")
            if source["version"] != checked.source_run_version or source["status"] not in (
                "completed", "partial"
            ):
                raise ValueError("memory source is not the terminal version")
            try:
                operation = json.loads(source["research_context"]).get("operation", {})
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("invalid memory source context") from exc
            if not isinstance(operation, dict) or operation.get("active_operation_id"):
                raise ValueError("memory source has an active operation")
            existing = connection.execute(
                """SELECT payload, state_digest FROM research_memory_revisions
                   WHERE source_run_id = ? AND source_run_version = ?""",
                (checked.source_run_id, checked.source_run_version),
            ).fetchone()
            if existing is not None and existing["state_digest"] != checked.state_digest:
                raise ValueError("memory source version digest conflict")
            source_run = _from_row(source)
            if checked.question != source_run.query:
                raise ValueError("memory question source mismatch")
            try:
                state = ResearchState.from_dict(
                    source_run.research_context["claim_engine"],
                    known_evidence_ids=known_research_evidence_ids(source_run),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("invalid memory source state") from exc
            if state.mode != "active" or state_digest(state) != checked.state_digest:
                raise ValueError("memory source state digest mismatch")
            if existing is not None:
                return ResearchMemoryRevision.from_dict(json.loads(existing["payload"]))
            connection.execute(
                """INSERT OR IGNORE INTO research_memory_threads(owner_thread_id)
                   VALUES (?)""",
                (checked.owner_thread_id,),
            )
            updated = connection.execute(
                """UPDATE research_memory_threads SET version = version + 1
                   WHERE owner_thread_id = ? AND version = ?""",
                (checked.owner_thread_id, expected_cursor_version),
            )
            if updated.rowcount != 1:
                raise ValueError("memory cursor conflict")
            if checked.prior_revision_ids:
                rows = connection.execute(
                    """SELECT revision_id FROM research_memory_revisions
                       WHERE owner_thread_id = ? AND revision_id IN
                       (""" + ",".join("?" for _ in checked.prior_revision_ids) + ")",
                    (checked.owner_thread_id, *checked.prior_revision_ids),
                ).fetchall()
                if {row["revision_id"] for row in rows} != set(checked.prior_revision_ids):
                    raise ValueError("memory prior revision owner mismatch")
            connection.execute(
                """INSERT INTO research_memory_revisions(
                   revision_id, owner_thread_id, source_run_id, source_run_version,
                   state_digest, schema_version, generated_at, payload
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    checked.revision_id, checked.owner_thread_id,
                    checked.source_run_id, checked.source_run_version,
                    checked.state_digest, checked.schema_version, checked.generated_at,
                    json.dumps(checked.to_dict(), ensure_ascii=False, sort_keys=True),
                ),
            )
        return checked

    def recall(
        self, owner_thread_id: str, question: str, *, today: date,
        limit: int = 20,
    ) -> tuple[RecallCandidate, ...]:
        if not owner_thread_id:
            raise ValueError("owner thread required")
        safe_limit = max(1, min(limit, 20))
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT memory.revision_id, memory.schema_version, memory.payload,
                          memory.source_run_id, memory.source_run_version,
                          source.id AS live_source_id, source.version AS live_source_version,
                          source.owner_thread_id AS live_owner_thread_id
                   FROM research_memory_revisions AS memory
                   LEFT JOIN web_lookup_runs AS source ON source.id = memory.source_run_id
                   WHERE memory.owner_thread_id = ?
                   ORDER BY memory.generated_at DESC, memory.revision_id DESC LIMIT ?""",
                (owner_thread_id, safe_limit),
            ).fetchall()
        topic = normalized_topic(question)
        result: list[RecallCandidate] = []
        for row in rows:
            if (
                row["live_source_id"] is None
                or row["live_source_version"] != row["source_run_version"]
                or row["live_owner_thread_id"] != owner_thread_id
            ):
                result.append(RecallCandidate(row["revision_id"], "unavailable", "memory_source_unavailable"))
                continue
            if row["schema_version"] != "research-memory-v1":
                result.append(RecallCandidate(row["revision_id"], "unavailable", "unsupported_memory_schema"))
                continue
            try:
                revision = ResearchMemoryRevision.from_dict(json.loads(row["payload"]))
                if (
                    revision.revision_id != row["revision_id"]
                    or revision.owner_thread_id != owner_thread_id
                    or revision.source_run_id != row["source_run_id"]
                    or revision.source_run_version != row["source_run_version"]
                    or any(not ref.source and not ref.locator for ref in revision.evidence_refs)
                ):
                    raise ValueError("memory row identity mismatch")
            except (TypeError, ValueError, KeyError):
                result.append(RecallCandidate(row["revision_id"], "unavailable", "invalid_memory_revision"))
                continue
            result.append(RecallCandidate(
                revision.revision_id, "available", "historical_lead_only",
                "same_topic" if topic and topic == revision.topic else "unverified",
                revision_freshness(revision, today=today), revision,
            ))
        return tuple(result)
