"""Persistent research authorizations (Async Deep-1A).

A run's entitlement is a durable row, created only by an explicit user action.
The original grant is **immutable**; a re-authorisation inserts a *new* grant that
supersedes it and binds the same run, so cumulative consumption, reserved money
and the global account balance are never re-granted by recovery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.domain.runtime_entities import ResearchAuthorization, new_id, utc_now

MICROS_PER_CNY = 1_000_000

TERMINAL_AUTHORIZATION_STATUSES = frozenset({"superseded", "revoked", "exhausted"})


def cny_to_micros(amount_cny: float) -> int:
    """Ceiling conversion; money authority is integer micro-CNY, never REAL."""

    import math

    value = float(amount_cny)
    if not math.isfinite(value) or value < 0:
        raise ValueError("amount must be a finite non-negative number")
    return int(math.ceil(value * MICROS_PER_CNY))


def parse_deadline(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def is_within_deadline(grant: ResearchAuthorization, *, now: datetime | None = None) -> bool:
    moment = now or datetime.now(timezone.utc)
    return moment < parse_deadline(grant.deadline_at)


class AuthorizationError(RuntimeError):
    """Raised when an authorization cannot be created or used."""


class ResearchAuthorizationRepository:
    def __init__(self, database: Any) -> None:
        self.database = database
        self.database.initialize()

    # -- reads ------------------------------------------------------------
    def get(self, authorization_id: str) -> ResearchAuthorization | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_authorizations WHERE id = ?", (authorization_id,)
            ).fetchone()
        return _from_row(row) if row else None

    def active_for_run(self, run_id: str) -> ResearchAuthorization | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_authorizations
                WHERE run_id = ? AND status = 'active'
                ORDER BY authorization_version DESC, created_at DESC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return _from_row(row) if row else None

    def any_for_run(self, run_id: str) -> ResearchAuthorization | None:
        """Any grant ever issued for this run (used to detect an async run)."""

        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM research_authorizations
                WHERE run_id = ? ORDER BY authorization_version DESC, created_at DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return _from_row(row) if row else None

    def remaining_micros(self, authorization_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT max_spend_micros, reserved_micros FROM research_authorizations WHERE id = ?",
                (authorization_id,),
            ).fetchone()
        if row is None:
            raise AuthorizationError(f"authorization not found: {authorization_id}")
        return int(row["max_spend_micros"]) - int(row["reserved_micros"])

    # -- writes -----------------------------------------------------------
    def create_grant(
        self,
        *,
        owner_thread_id: str,
        deadline_at: str,
        max_model_calls: int,
        max_vision_calls: int,
        max_searches: int,
        max_reads: int,
        max_spend_micros: int,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> ResearchAuthorization:
        """Create one user-authorized grant, superseding any active grant for the run."""

        if not str(owner_thread_id).strip():
            raise AuthorizationError("owner_thread_id is required")
        if max_spend_micros < 0:
            raise AuthorizationError("max_spend_micros must be non-negative")
        moment = now or datetime.now(timezone.utc)
        timestamp = moment.isoformat()
        grant = ResearchAuthorization(
            id=new_id("auth"),
            owner_thread_id=str(owner_thread_id),
            run_id=run_id,
            granted_at=timestamp,
            deadline_at=deadline_at,
            authorization_version=1,
            status="active",
            max_model_calls=int(max_model_calls),
            max_vision_calls=int(max_vision_calls),
            max_searches=int(max_searches),
            max_reads=int(max_reads),
            max_spend_micros=int(max_spend_micros),
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_version = 0
            previous_id: str | None = None
            # Cumulative usage stays authoritative across re-authorisation: the new
            # grant continues from the run's already-reserved/settled/executed
            # facts instead of resetting them (a new grant is a *total* ceiling).
            carried_reserved = 0
            carried_settled = 0
            carried_seconds = 0.0
            if run_id:
                prior = connection.execute(
                    """
                    SELECT id, authorization_version, reserved_micros, settled_micros,
                           executed_seconds
                    FROM research_authorizations
                    WHERE run_id = ? AND status = 'active'
                    ORDER BY authorization_version DESC LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                if prior is not None:
                    previous_version = int(prior["authorization_version"])
                    previous_id = str(prior["id"])
                    carried_reserved = int(prior["reserved_micros"])
                    carried_settled = int(prior["settled_micros"])
                    carried_seconds = float(prior["executed_seconds"])
                    connection.execute(
                        "UPDATE research_authorizations SET status = 'superseded', updated_at = ? WHERE id = ?",
                        (timestamp, previous_id),
                    )
            connection.execute(
                """
                INSERT INTO research_authorizations(
                    id, owner_thread_id, run_id, granted_at, deadline_at, authorization_version,
                    supersedes_authorization_id, status, max_model_calls, max_vision_calls,
                    max_searches, max_reads, max_spend_micros, reserved_micros, settled_micros,
                    executed_seconds, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grant.id, grant.owner_thread_id, run_id, grant.granted_at, grant.deadline_at,
                    previous_version + 1, previous_id, grant.max_model_calls, grant.max_vision_calls,
                    grant.max_searches, grant.max_reads, grant.max_spend_micros,
                    carried_reserved, carried_settled, carried_seconds, timestamp, timestamp,
                ),
            )
            connection.commit()
        return self.get(grant.id) or grant

    def run_usage(self, run_id: str) -> dict[str, float]:
        """Cumulative run usage across every grant (authoritative, never reset)."""

        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS grants,
                       COALESCE(SUM(reserved_micros), 0) AS reserved,
                       COALESCE(SUM(settled_micros), 0) AS settled,
                       COALESCE(SUM(executed_seconds), 0) AS seconds
                FROM research_authorizations WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        return {
            "grants": float(row["grants"]),
            "reserved_micros": float(row["reserved"]),
            "settled_micros": float(row["settled"]),
            "executed_seconds": float(row["seconds"]),
        }

    def bind_run(self, authorization_id: str, run_id: str) -> ResearchAuthorization:
        """Bind a (possibly pre-existing) grant to its run."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE research_authorizations SET run_id = ?, updated_at = ? WHERE id = ?",
                (run_id, utc_now(), authorization_id),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise AuthorizationError(f"authorization not found: {authorization_id}")
            connection.commit()
        grant = self.get(authorization_id)
        if grant is None:
            raise AuthorizationError(f"authorization not found: {authorization_id}")
        return grant

    def add_executed_seconds(self, authorization_id: str, seconds: float) -> None:
        """Accumulate real execution time (never reset by recovery)."""

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE research_authorizations
                SET executed_seconds = executed_seconds + ?, updated_at = ?
                WHERE id = ?
                """,
                (max(0.0, float(seconds)), utc_now(), authorization_id),
            )

    def mark_exhausted(self, authorization_id: str, *, reason: str = "") -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE research_authorizations SET status = 'exhausted', updated_at = ? WHERE id = ?",
                (utc_now(), authorization_id),
            )

    def revoke(self, authorization_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE research_authorizations SET status = 'revoked', updated_at = ? WHERE id = ?",
                (utc_now(), authorization_id),
            )


def _from_row(row: Any) -> ResearchAuthorization:
    return ResearchAuthorization(
        id=row["id"],
        owner_thread_id=row["owner_thread_id"],
        run_id=row["run_id"],
        granted_at=row["granted_at"],
        deadline_at=row["deadline_at"],
        authorization_version=int(row["authorization_version"]),
        supersedes_authorization_id=row["supersedes_authorization_id"],
        status=row["status"],
        max_model_calls=int(row["max_model_calls"]),
        max_vision_calls=int(row["max_vision_calls"]),
        max_searches=int(row["max_searches"]),
        max_reads=int(row["max_reads"]),
        max_spend_micros=int(row["max_spend_micros"]),
        reserved_micros=int(row["reserved_micros"]),
        settled_micros=int(row["settled_micros"]),
        executed_seconds=float(row["executed_seconds"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
