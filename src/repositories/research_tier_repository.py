"""CL-M3 QD-3d: the durable record of a user's permission to spend more.

The contract froze this on 2026-10-24 (CL_M3_CAPABILITY_CONTRACT.md §11.3):
a tier upgrade is a **user permission decision**, recorded in **its own
table**, and a *request* is not an *approval*.

**Why the request and the decision are two rows.** The model may ask to move
up a tier; only the user may grant it. If one row held both, the asking would
be indistinguishable from the granting, and the first thing nobody could
tell apart would be the thing that costs money.

**Why the checks live here and not at the call sites.** ``apply_upgrade`` is
the only way a tier changes, and it re-verifies everything before it writes:
that the authorisation exists, that it was approved, that it has not expired,
that it belongs to this research, and that it belongs to this *operation
identity*. A grant made for one operation does not carry into another - a
research that was resumed, retried or re-run under a new operation is a
different run, and a user's "yes, for this one" is not a blank cheque.

**The absence of a record means no.** A missing authorisation is not a
probably-fine; it is a refusal. This is the difference between a guard and a
hint, and it is the whole reason the table exists.

**The event log is not involved.** QD-3c established that the event log is a
projection and not a second truth. The same discipline applies here: the log
may carry an audit trail of who asked and who decided, but the authority for
an upgrade is this table.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.domain.research_authorization import (
    AUTHORIZATION_APPROVED,
    AUTHORIZATION_DENIED,
    AUTHORIZATION_EXPIRED,
    AUTHORIZATION_PENDING,
    TIER_DEEP,
    TIER_STANDARD,
    TIERS,
    TierAuthorization,
    TierUpgradeRequest,
)
from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase


class TierAuthorizationDenied(ValueError):
    """No valid authorisation allows this upgrade.

    The single refusal the whole module exists to produce. It is raised for a
    missing record, an unapproved one, an expired one, one that belongs to a
    different operation, and one whose ceiling is too small - because the
    caller has one decision to make and the reason is for the log, not for the
    branch.
    """


class ResearchTierRepository:
    """Tier-upgrade requests and the user's decisions on them."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database

    # --- requests -----------------------------------------------------------------

    def request_upgrade(
        self,
        research_id: str,
        *,
        operation_id: str,
        from_tier: str,
        to_tier: str,
        reason: str = "",
        requested_calls: int = 0,
        requested_cost: float = 0.0,
        request_id: str = "",
        now: str | None = None,
    ) -> TierUpgradeRequest:
        """Record a research's request to move up a tier.

        This grants nothing. The row it writes says ``pending``, and pending
        is the state in which an upgrade is refused.
        """

        if from_tier not in TIERS:
            raise ValueError("invalid_from_tier")
        if to_tier not in TIERS:
            raise ValueError("invalid_to_tier")
        if type(requested_calls) is not int or requested_calls < 0:
            raise ValueError("invalid_requested_calls")
        if isinstance(requested_cost, bool) or not isinstance(requested_cost, (int, float)):
            raise ValueError("invalid_requested_cost")
        if requested_cost < 0:
            raise ValueError("invalid_requested_cost")
        moment = now or utc_now()
        identifier = request_id or f"tierreq-{research_id}-{moment}"
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM research_states WHERE research_id = ?", (research_id,)
            ).fetchone()
            if exists is None:
                raise TierAuthorizationDenied("research_not_found")
            connection.execute(
                "INSERT INTO research_tier_upgrade_requests ("
                "request_id, research_id, operation_id, from_tier, to_tier, reason, "
                "requested_calls, requested_cost, status, requested_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier,
                    research_id,
                    operation_id,
                    from_tier,
                    to_tier,
                    reason,
                    requested_calls,
                    float(requested_cost),
                    AUTHORIZATION_PENDING,
                    moment,
                ),
            )
        return TierUpgradeRequest(
            request_id=identifier,
            research_id=research_id,
            operation_id=operation_id,
            from_tier=from_tier,
            to_tier=to_tier,
            reason=reason,
            requested_calls=requested_calls,
            requested_cost=float(requested_cost),
            status=AUTHORIZATION_PENDING,
            requested_at=moment,
        )

    # --- decisions ----------------------------------------------------------------

    def approve(
        self,
        request_id: str,
        *,
        approver: str,
        scope: str = "",
        valid_until: str = "",
        max_calls: int = 0,
        max_cost: float = 0.0,
        now: str | None = None,
    ) -> TierAuthorization:
        """Record the user's approval. The only path into ``approved``."""

        return self._decide(
            request_id,
            status=AUTHORIZATION_APPROVED,
            approver=approver,
            scope=scope,
            valid_until=valid_until,
            max_calls=max_calls,
            max_cost=max_cost,
            now=now,
        )

    def deny(
        self,
        request_id: str,
        *,
        approver: str,
        scope: str = "",
        reason: str = "",
        now: str | None = None,
    ) -> TierAuthorization:
        """Record the user's refusal."""

        return self._decide(
            request_id,
            status=AUTHORIZATION_DENIED,
            approver=approver,
            scope=scope or reason,
            valid_until="",
            max_calls=0,
            max_cost=0.0,
            now=now,
        )

    def _decide(
        self,
        request_id: str,
        *,
        status: str,
        approver: str,
        scope: str,
        valid_until: str,
        max_calls: int,
        max_cost: float,
        now: str | None,
    ) -> TierAuthorization:
        moment = now or utc_now()
        with self.database.connect() as connection:
            request = connection.execute(
                "SELECT * FROM research_tier_upgrade_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if request is None:
                raise TierAuthorizationDenied("unknown_request")
            if request["status"] != AUTHORIZATION_PENDING:
                # A decision may only be made on a request that has not been
                # decided. Deciding twice would make the record ambiguous.
                raise TierAuthorizationDenied("request_already_decided")
            connection.execute(
                "INSERT INTO research_tier_authorizations ("
                "request_id, research_id, operation_id, status, approver, scope, "
                "valid_until, max_calls, max_cost, decided_at, requested_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id,
                    request["research_id"],
                    request["operation_id"],
                    status,
                    approver,
                    scope,
                    valid_until,
                    max_calls,
                    float(max_cost),
                    moment,
                    request["requested_at"],
                ),
            )
            connection.execute(
                "UPDATE research_tier_upgrade_requests SET status = ? WHERE request_id = ?",
                (status, request_id),
            )
        return TierAuthorization(
            request_id=request_id,
            research_id=request["research_id"],
            operation_id=request["operation_id"],
            status=status,
            approver=approver,
            scope=scope,
            valid_until=valid_until,
            max_calls=max_calls,
            max_cost=float(max_cost),
            decided_at=moment,
            requested_at=request["requested_at"],
        )

    # --- reads --------------------------------------------------------------------

    def authorization(self, request_id: str) -> TierAuthorization | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_tier_authorizations WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return None if row is None else _authorization_from_row(row)

    def requests_for(self, research_id: str) -> tuple[TierUpgradeRequest, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_tier_upgrade_requests WHERE research_id = ? "
                "ORDER BY requested_at ASC",
                (research_id,),
            ).fetchall()
        return tuple(_request_from_row(row) for row in rows)

    def latest_authorization(self, research_id: str) -> TierAuthorization | None:
        """The most recent decision for this research, if there is one."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_tier_authorizations "
                "WHERE research_id = ? ORDER BY decided_at DESC LIMIT 1",
                (research_id,),
            ).fetchone()
        return None if row is None else _authorization_from_row(row)

    # --- the one way a tier changes -------------------------------------------------

    def apply_upgrade(
        self,
        research_id: str,
        *,
        operation_id: str,
        calls: int = 0,
        cost: float = 0.0,
        now: str | None = None,
    ) -> Any:
        """Raise a research's tier, if a valid authorisation allows it.

        Everything is re-verified here, at the moment of the change, rather
        than trusted from an earlier read. An authorisation that was valid
        when it was granted may have expired, may belong to a different
        operation, or may not be big enough for what is being spent now.

        Returns the updated research state, or raises
        ``TierAuthorizationDenied`` - which is the *only* refusal this
        module produces, because a caller that has to distinguish "expired"
        from "missing" from "too small" will eventually handle one of them
        by continuing.
        """

        moment = now or utc_now()
        with self.database.connect() as connection:
            state = connection.execute(
                "SELECT * FROM research_states WHERE research_id = ?", (research_id,)
            ).fetchone()
            if state is None:
                raise TierAuthorizationDenied("research_not_found")
            if state["cancel_requested_at"]:
                # A cancelled research must not be able to spend more.
                raise TierAuthorizationDenied("research_cancelled")
            if state["status"] in {"cancelled", "failed", "stopped"}:
                raise TierAuthorizationDenied("research_terminal")

            authorization = connection.execute(
                "SELECT * FROM research_tier_authorizations "
                "WHERE research_id = ? AND status = ? "
                "ORDER BY decided_at DESC LIMIT 1",
                (research_id, AUTHORIZATION_APPROVED),
            ).fetchone()
            if authorization is None:
                raise TierAuthorizationDenied("no_authorization")
            if authorization["operation_id"] != operation_id:
                raise TierAuthorizationDenied("operation_mismatch")

            record = _authorization_from_row(authorization)
            if not record.is_valid_at(moment):
                raise TierAuthorizationDenied("authorization_expired")
            if not record.covers(calls, cost):
                raise TierAuthorizationDenied("authorization_too_small")

            target = connection.execute(
                "SELECT to_tier FROM research_tier_upgrade_requests WHERE request_id = ?",
                (record.request_id,),
            ).fetchone()
            if target is None:
                raise TierAuthorizationDenied("unknown_request")
            to_tier = target["to_tier"]
            if to_tier not in TIERS:
                raise TierAuthorizationDenied("invalid_target_tier")

            connection.execute(
                "UPDATE research_states SET tier = ?, tier_upgrade_authorized = 1, "
                "state_version = state_version + 1, updated_at = ? "
                "WHERE research_id = ?",
                (to_tier, moment, research_id),
            )

        from src.repositories.research_state_repository import ResearchStateRepository

        updated = ResearchStateRepository(self.database).load(research_id)
        if updated is None:  # pragma: no cover
            raise TierAuthorizationDenied("research_not_found")
        return updated

    def expire(self, request_id: str, *, now: str | None = None) -> TierAuthorization:
        """Mark an authorisation as expired.

        The clock alone may do this - an expired grant is not a decision, it
        is the absence of one - but writing it down keeps the record honest
        for anyone auditing it later.

        Two refusals, and they are the point of the method:

        - A grant that has not reached its deadline cannot be expired. The
          expiry moment is the deadline the grant already carries
          (``valid_until``), so expiring it early would be a revocation
          dressed as a clock event - and a revocation is a decision, which
          belongs to the user and is recorded elsewhere.
        - A grant that was never approved has nothing to expire.

        Both rows move together. The request row and the authorisation row
        describe the same decision, and a table that says "expired" next to a
        table that says "approved" is the second-truth problem this whole
        module exists to avoid.
        """

        moment = now or utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM research_tier_authorizations WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise TierAuthorizationDenied("unknown_request")
            record = _authorization_from_row(row)
            if not record.approved:
                raise TierAuthorizationDenied("authorization_not_approved")
            if not record.has_expired(moment):
                raise TierAuthorizationDenied("authorization_not_expired")
            connection.execute(
                "UPDATE research_tier_authorizations SET status = ? WHERE request_id = ?",
                (AUTHORIZATION_EXPIRED, request_id),
            )
            connection.execute(
                "UPDATE research_tier_upgrade_requests SET status = ? WHERE request_id = ?",
                (AUTHORIZATION_EXPIRED, request_id),
            )
        return TierAuthorization(
            request_id=record.request_id,
            research_id=record.research_id,
            operation_id=record.operation_id,
            status=AUTHORIZATION_EXPIRED,
            approver=record.approver,
            scope=record.scope,
            valid_until=record.valid_until,
            max_calls=record.max_calls,
            max_cost=record.max_cost,
            decided_at=record.decided_at,
            requested_at=record.requested_at,
        )


def _request_from_row(row: sqlite3.Row) -> TierUpgradeRequest:
    return TierUpgradeRequest(
        request_id=row["request_id"],
        research_id=row["research_id"],
        operation_id=row["operation_id"],
        from_tier=row["from_tier"],
        to_tier=row["to_tier"],
        reason=row["reason"],
        requested_calls=row["requested_calls"],
        requested_cost=row["requested_cost"],
        status=row["status"],
        requested_at=row["requested_at"],
    )


def _authorization_from_row(row: sqlite3.Row) -> TierAuthorization:
    return TierAuthorization(
        request_id=row["request_id"],
        research_id=row["research_id"],
        operation_id=row["operation_id"],
        status=row["status"],
        approver=row["approver"],
        scope=row["scope"],
        valid_until=row["valid_until"],
        max_calls=row["max_calls"],
        max_cost=row["max_cost"],
        decided_at=row["decided_at"],
        requested_at=row["requested_at"],
    )


__all__ = [
    "AUTHORIZATION_APPROVED",
    "AUTHORIZATION_DENIED",
    "AUTHORIZATION_EXPIRED",
    "AUTHORIZATION_PENDING",
    "TIER_DEEP",
    "TIER_STANDARD",
    "ResearchTierRepository",
    "TierAuthorizationDenied",
]
