"""Durable two-tier spend ledger (Async Deep-1A).

Money authority is **integer micro-CNY** (never SQLite REAL).  A reservation is
validated and written atomically against both the run authorization balance and
the account-wide balance, so concurrent runs cannot each spend the full budget.

Idempotency is by ``call_id`` **plus full identity**: a different authorization,
purpose, model, estimate or request fingerprint under the same ``call_id`` is a
conflict, not a cache hit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.domain.runtime_entities import utc_now

STATES = frozenset({"reserved", "sent", "settled", "orphaned"})


class SpendLimitExceeded(RuntimeError):
    """A request would exceed the run authorization or the account ceiling."""


class SpendIdentityConflict(RuntimeError):
    """The same call_id was reused for a different request identity."""


@dataclass(frozen=True)
class SpendReservation:
    call_id: str
    authorization_id: str
    scope_id: str
    reserved_micros: int
    state: str
    created: bool


def fingerprint(*, purpose: str, model: str, scope_id: str, estimated_micros: int,
                extra: dict[str, Any] | None = None) -> str:
    payload = json.dumps(
        {
            "purpose": purpose,
            "model": model,
            "scope_id": scope_id,
            "estimated_micros": int(estimated_micros),
            "extra": extra or {},
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SpendLedgerRepository:
    def __init__(self, database: Any) -> None:
        self.database = database
        self.database.initialize()

    # -- account ----------------------------------------------------------
    def ensure_account(self, limit_micros: int, *, account_id: str = "account") -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO llm_spend_accounts(id, limit_micros, reserved_micros, settled_micros)
                VALUES (?, ?, 0, 0)
                ON CONFLICT(id) DO UPDATE SET limit_micros = excluded.limit_micros
                """,
                (account_id, int(limit_micros)),
            )

    def global_remaining_micros(self, *, account_id: str = "account") -> int | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT limit_micros, reserved_micros FROM llm_spend_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if row is None:
            return None
        return int(row["limit_micros"]) - int(row["reserved_micros"])

    # -- reservation ------------------------------------------------------
    def reserve(
        self,
        *,
        call_id: str,
        authorization_id: str,
        scope_id: str,
        purpose: str,
        model: str,
        estimated_micros: int,
        extra: dict[str, Any] | None = None,
        account_id: str = "account",
        lease: tuple[str, int] | None = None,
    ) -> SpendReservation:
        if not call_id.strip() or not authorization_id.strip():
            raise ValueError("call_id and authorization_id are required")
        estimate = int(estimated_micros)
        if estimate < 0:
            raise ValueError("estimated_micros must be non-negative")
        stamp = fingerprint(purpose=purpose, model=model, scope_id=scope_id,
                            estimated_micros=estimate, extra=extra)
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if lease is not None:
                # 1B-R1: authority to spend belongs to the current lease holder.
                # A worker that was superseded keeps a valid authorization and a
                # healthy balance, so the authorization check alone would let it
                # start new paid requests.  Verify the fence here, atomically, so a
                # stale execution identity can never pay.
                run_row = connection.execute(
                    "SELECT lease_holder, lease_epoch, lease_expires_at "
                    "FROM web_lookup_runs WHERE id = ?",
                    (scope_id,),
                ).fetchone()
                if run_row is None:
                    connection.rollback()
                    raise SpendLimitExceeded(f"unknown run for a lease-fenced call: {scope_id}")
                if str(run_row["lease_holder"] or "") != str(lease[0]) or int(
                    run_row["lease_epoch"] or 0
                ) != int(lease[1]):
                    connection.rollback()
                    raise SpendLimitExceeded(
                        "paid call refused: this execution identity no longer holds the lease"
                    )
                expires = run_row["lease_expires_at"]
                if expires is not None and str(expires) <= now:
                    connection.rollback()
                    raise SpendLimitExceeded("paid call refused: the lease has expired")
            existing = connection.execute(
                "SELECT * FROM llm_spend_ledger WHERE call_id = ?", (call_id,)
            ).fetchone()
            if existing is not None:
                same_identity = (
                    str(existing["authorization_id"]) == authorization_id
                    and str(existing["scope_id"]) == scope_id
                    and str(existing["purpose"]) == purpose
                    and str(existing["model"]) == model
                    and int(existing["reserved_micros"]) == estimate
                    and str(existing["fingerprint"]) == stamp
                )
                if not same_identity:
                    connection.rollback()
                    raise SpendIdentityConflict(f"call_id reused with a different identity: {call_id}")
                connection.commit()
                return SpendReservation(
                    call_id=call_id, authorization_id=authorization_id, scope_id=scope_id,
                    reserved_micros=int(existing["reserved_micros"]),
                    state=str(existing["state"]), created=False,
                )

            grant = connection.execute(
                """
                SELECT max_spend_micros, reserved_micros, status, deadline_at, run_id
                FROM research_authorizations WHERE id = ?
                """,
                (authorization_id,),
            ).fetchone()
            if grant is None:
                connection.rollback()
                raise SpendLimitExceeded(f"authorization not found: {authorization_id}")
            # F2: an invalid, expired or mis-scoped authorization must fail closed.
            if str(grant["status"]) != "active":
                connection.rollback()
                raise SpendLimitExceeded(f"authorization is not active: {grant['status']}")
            deadline = grant["deadline_at"]
            if deadline:
                from datetime import datetime, timezone

                moment = datetime.now(timezone.utc)
                if moment >= datetime.fromisoformat(str(deadline).replace("Z", "+00:00")):
                    connection.rollback()
                    raise SpendLimitExceeded("authorization has expired")
            bound_run = grant["run_id"]
            if bound_run is not None and str(bound_run) != str(scope_id):
                connection.rollback()
                raise SpendLimitExceeded(
                    f"authorization is bound to run {bound_run}, not scope {scope_id}"
                )
            run_remaining = int(grant["max_spend_micros"]) - int(grant["reserved_micros"])
            account = connection.execute(
                "SELECT limit_micros, reserved_micros FROM llm_spend_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if account is None:
                # F2: no account ceiling means no authority to spend; never open-ended.
                connection.rollback()
                raise SpendLimitExceeded("account ceiling is not configured")
            account_remaining = int(account["limit_micros"]) - int(account["reserved_micros"])
            if estimate > run_remaining or estimate > account_remaining:
                connection.rollback()
                raise SpendLimitExceeded(
                    f"spend limit: estimate={estimate} run_remaining={run_remaining} "
                    f"account_remaining={account_remaining}"
                )
            connection.execute(
                """
                INSERT INTO llm_spend_ledger(
                    call_id, authorization_id, scope_kind, scope_id, purpose, model,
                    fingerprint, reserved_micros, settled_micros, state, created_at, updated_at
                ) VALUES (?, ?, 'run', ?, ?, ?, ?, ?, NULL, 'reserved', ?, ?)
                """,
                (call_id, authorization_id, scope_id, purpose, model, stamp, estimate, now, now),
            )
            connection.execute(
                """
                UPDATE research_authorizations
                SET reserved_micros = reserved_micros + ?, updated_at = ?
                WHERE id = ?
                """,
                (estimate, now, authorization_id),
            )
            connection.execute(
                "UPDATE llm_spend_accounts SET reserved_micros = reserved_micros + ? WHERE id = ?",
                (estimate, account_id),
            )
            connection.commit()
        return SpendReservation(call_id=call_id, authorization_id=authorization_id,
                                scope_id=scope_id, reserved_micros=estimate,
                                state="reserved", created=True)

    # -- lifecycle --------------------------------------------------------
    def state(self, call_id: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT state FROM llm_spend_ledger WHERE call_id = ?", (call_id,)
            ).fetchone()
        return str(row["state"]) if row else None

    def mark_sent(self, call_id: str) -> None:
        """Persist the send *intent* before the request leaves the process."""

        with self.database.connect() as connection:
            connection.execute(
                "UPDATE llm_spend_ledger SET state = 'sent', updated_at = ? "
                "WHERE call_id = ? AND state = 'reserved'",
                (utc_now(), call_id),
            )

    def settle(self, call_id: str, *, actual_micros: int) -> None:
        """Record real consumption for audit; the reservation itself is not refunded."""

        with self.database.connect() as connection:
            connection.execute(
                "UPDATE llm_spend_ledger SET state = 'settled', settled_micros = ?, updated_at = ? "
                "WHERE call_id = ? AND state IN ('reserved', 'sent')",
                (int(actual_micros), utc_now(), call_id),
            )

    def mark_orphaned(self, call_id: str) -> None:
        """A crashed reservation whose request was never confirmed sent.

        The reservation is kept (no refund); the call is never auto-resent.
        """

        with self.database.connect() as connection:
            connection.execute(
                "UPDATE llm_spend_ledger SET state = 'orphaned', updated_at = ? "
                "WHERE call_id = ? AND state = 'reserved'",
                (utc_now(), call_id),
            )

    def unconfirmed_sends(self) -> list[str]:
        """Call ids whose send was persisted but whose outcome is unknown."""

        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT call_id FROM llm_spend_ledger WHERE state = 'sent' ORDER BY created_at"
            ).fetchall()
        return [str(row["call_id"]) for row in rows]
