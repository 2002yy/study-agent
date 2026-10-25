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
    is_finite_number,
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

    The reason is a **first-class attribute**, not just the message. The
    refusals are different facts - "there is no record", "this grant was
    never approved", "this grant has not expired" - and a caller that has to
    tell them apart cannot do it from ``str(exc)`` alone without depending on
    the exact wording. Keeping it as ``reason`` also makes the distinction
    testable: a guard that refuses for the *wrong* reason is not the guard
    that was written.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
        reason: str,
        requested_calls: int = 0,
        requested_cost: float = 0.0,
        request_id: str = "",
        now: str | None = None,
    ) -> TierUpgradeRequest:
        """Record a research's request to move up a tier.

        This grants nothing. The row it writes says ``pending``, and pending
        is the state in which an upgrade is refused.

        **Validation finishes before the write, and the write returns the very
        object it validated.** The fields are checked by *constructing the
        record* and inserting only that instance. An earlier shape validated
        the tiers and the counts here, inserted the row, and then built
        ``TierUpgradeRequest`` - so the record's own checks (a finite
        ``requested_cost``, a non-empty ``reason``, identifiers, the
        timestamp) ran after the commit. ``requested_cost=inf`` or the empty
        default ``reason`` therefore raised with the request already stored: a
        caller saw a failure it could retry, and the retry collided with a
        request that had never been successfully made. Checking fields one by
        one here would keep drifting out of step with the record; building the
        record is the check.

        ``reason`` is required and non-empty because it is the part of the
        request the user answers. A request that cannot say why it wants more
        budget is not a question a user can decide.
        """

        moment = now or utc_now()
        identifier = request_id or f"tierreq-{research_id}-{moment}"
        # Constructing the record is the validation: every field is checked by
        # the domain's own rules, and nothing reaches the database until it
        # has passed all of them.
        request = TierUpgradeRequest(
            request_id=identifier,
            research_id=research_id,
            operation_id=operation_id,
            from_tier=from_tier,
            to_tier=to_tier,
            reason=reason,
            requested_calls=requested_calls,
            requested_cost=requested_cost,
            status=AUTHORIZATION_PENDING,
            requested_at=moment,
        )
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM research_states WHERE research_id = ?", (request.research_id,)
            ).fetchone()
            if exists is None:
                raise TierAuthorizationDenied("research_not_found")
            connection.execute(
                "INSERT INTO research_tier_upgrade_requests ("
                "request_id, research_id, operation_id, from_tier, to_tier, reason, "
                "requested_calls, requested_cost, status, requested_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.request_id,
                    request.research_id,
                    request.operation_id,
                    request.from_tier,
                    request.to_tier,
                    request.reason,
                    request.requested_calls,
                    float(request.requested_cost),
                    request.status,
                    request.requested_at,
                ),
            )
        return request

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
        """Record the user's approval. The only path into ``approved``.

        **An approval must say when it ends and how much it allows.** The
        contract's record for an authorisation decision carries "有效期、费用
        上限" - an expiry and a cost ceiling - and §11.3 requires the ceiling
        to be re-verified against every upgrade. An approval with neither is
        not a bounded permission; it is a blank cheque.

        This matters because the ceiling check used to be conditional on the
        ceiling being there: ``if self.max_calls and calls > self.max_calls``
        skips the comparison entirely when ``max_calls`` is 0. So the two
        halves of the hole reinforced each other - an approval could be
        recorded without a ceiling, and a ceiling of zero meant "no limit"
        rather than "no allowance".

        The refusal happens **before** anything is written. A malformed
        approval must not leave a decision behind, and the request stays
        ``pending`` - which is not the same thing as a denial, because the
        user never said no.
        """

        if not valid_until:
            raise TierAuthorizationDenied("authorization_missing_expiry")
        if max_calls <= 0 or max_cost <= 0:
            raise TierAuthorizationDenied("authorization_missing_ceiling")
        # A ceiling of infinity is not a ceiling, and NaN is worse: it fails
        # every comparison, so `cost > max_cost` would never fire and the
        # grant would cover every spend. `max_cost <= 0` cannot catch either
        # - `inf <= 0` is False and every comparison against NaN is False -
        # so the refusal has to state the finiteness question itself. The
        # refusal happens before anything is written, like the two above.
        if not is_finite_number(max_calls) or not is_finite_number(max_cost):
            raise TierAuthorizationDenied("authorization_non_finite_ceiling")
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

        **The identity is checked against the research, not against the
        caller.** The authorisation's ``operation_id`` is compared to the
        one the *research row* carries, and the one the caller passes must
        match that row too. The old code compared the authorisation to the
        caller's argument and never looked at the research's own
        ``operation_id`` - so an approval made for a different operation
        could be redeemed on a research that belonged to another one, as
        long as the caller quoted the right string.

        **The write carries the conditions, not just the read.** The checks
        above are a read; the statement below is the write; a cancellation
        that lands between them used to be invisible to both. The write
        therefore repeats the conditions in its ``WHERE`` clause and refuses
        to claim a row it did not actually change - the same shape as
        ``stop_if_no_progress`` in the state repository.

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
            if state["operation_id"] != operation_id:
                # The caller is not acting for this research's operation.
                raise TierAuthorizationDenied("operation_mismatch")

            authorization = connection.execute(
                "SELECT * FROM research_tier_authorizations "
                "WHERE research_id = ? AND status = ? "
                "ORDER BY decided_at DESC LIMIT 1",
                (research_id, AUTHORIZATION_APPROVED),
            ).fetchone()
            if authorization is None:
                raise TierAuthorizationDenied("no_authorization")
            if authorization["operation_id"] != state["operation_id"]:
                # The grant belongs to a different operation than the one
                # this research is actually running under.
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

            # The conditions are repeated here on purpose. The read above
            # and this write are separate statements, and a cancellation
            # that lands between them must not be able to slip through.
            cursor = connection.execute(
                "UPDATE research_states SET tier = ?, tier_upgrade_authorized = 1, "
                "state_version = state_version + 1, updated_at = ? "
                "WHERE research_id = ? AND state_version = ? "
                "AND status IN ('running', 'checkpointed') "
                "AND cancel_requested_at = ''",
                (to_tier, moment, research_id, state["state_version"]),
            )
            if cursor.rowcount != 1:
                # A cancellation, a terminal decision or another writer won
                # the race. The research keeps its old tier - the decision
                # that arrived first is the one that stands.
                #
                # The reason is read back rather than guessed, because the
                # refusals are different facts and a caller that cannot tell
                # them apart will handle one of them by continuing.
                current = connection.execute(
                    "SELECT status, cancel_requested_at FROM research_states "
                    "WHERE research_id = ?",
                    (research_id,),
                ).fetchone()
                if current is None:
                    raise TierAuthorizationDenied("research_not_found")
                if current["cancel_requested_at"]:
                    raise TierAuthorizationDenied("research_cancelled")
                if current["status"] in {"cancelled", "failed", "stopped"}:
                    raise TierAuthorizationDenied("research_terminal")
                raise TierAuthorizationDenied("research_state_changed")

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
