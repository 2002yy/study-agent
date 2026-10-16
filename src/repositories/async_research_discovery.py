"""Async Deep-1B restricted discovery entry.

Background async research must not be discoverable through the Standard→Deep
queue: :meth:`DeepTriggerRepository.discover` scans ``chat_turns`` and would let an
ordinary conversation arm paid work.  This module is the *only* entry that can hand
a run to the 1B background worker, and its boundary is the authorization:

* a candidate must join to an ``active`` authorization for that very run, so an
  unauthorized request can never enter paid background work;
* the pure eligibility predicate stays the single decider of *whether* the run may
  proceed (deadline, spend, retryability, real work left);
* the entry is read-only — it writes nothing, so the Standard→Deep queue and every
  existing ingress keep their exact previous behaviour.

Failing to read the authorization table raises: an entry that cannot prove a grant
must never widen into a general queue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.application.async_research_eligibility import is_eligible
from src.repositories.web_lookup_repository import _dump, _with_operation

#: Run states the worker may consider.  ``completed``/``cancelled`` are terminal.
CANDIDATE_STATUSES = ("pending", "running", "paused", "failed")


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value if isinstance(value, datetime) else None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class AsyncResearchCandidate:
    """One run the worker is allowed to try to lease."""

    run_id: str
    authorization_id: str
    status: str
    reason: str = ""


class ClaimRefused(RuntimeError):
    """The claim transaction refused to grant execution rights.

    ``reason`` is a stable token so callers can distinguish "try again" from
    "stop and ask the user", notably ``unconfirmed_paid_call``.
    """

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class AsyncResearchClaim:
    """Persisted execution rights: the worker's only authority to spend."""

    run_id: str
    authorization_id: str
    holder: str
    epoch: int
    expires_at: str


class _RunView:
    """Minimal run view for the eligibility predicate, built from one row.

    Reading the predicate inputs from the row inside the claim transaction avoids a
    second connection, so the decision uses exactly the state the write locked.
    """

    def __init__(self, row: Any) -> None:
        self.status = str(row["status"])
        self.stop_reason = str(row["stop_reason"] or "")
        self.research_context = json.loads(row["research_context"] or "{}")


class _GrantView:
    """Minimal grant view for the eligibility predicate."""

    def __init__(self, row: Any) -> None:
        self.status = str(row["status"])
        self.deadline_at = str(row["deadline_at"])
        self.max_spend_micros = int(row["max_spend_micros"])
        self.reserved_micros = int(row["reserved_micros"])


class AsyncResearchDiscovery:
    """Read-only, authorization-gated entry for the 1B background worker."""

    def __init__(
        self,
        database: Any,
        *,
        runs: Any,
        authorizations: Any,
    ) -> None:
        self.database = database
        self.runs = runs
        self.authorizations = authorizations

    def _candidate_rows(self, limit: int) -> list[Any]:
        placeholders = ", ".join("?" for _ in CANDIDATE_STATUSES)
        with self.database.connect() as connection:
            return connection.execute(
                f"""
                SELECT r.id AS run_id, a.id AS authorization_id
                FROM web_lookup_runs AS r
                JOIN research_authorizations AS a
                  ON a.run_id = r.id AND a.status = 'active'
                WHERE r.status IN ({placeholders})
                ORDER BY a.deadline_at ASC, r.id ASC
                LIMIT ?
                """,
                (*CANDIDATE_STATUSES, max(0, int(limit))),
            ).fetchall()

    @staticmethod
    def _lease_available(run: Any, now: datetime) -> bool:
        """True when no other holder can still claim this run.

        A holder without a usable expiry fails closed: an ambiguous lock must not
        be taken over, or two workers would both pay for the same run.
        """

        holder = getattr(run, "lease_holder", None)
        if not holder:
            return True
        expires = _parse_timestamp(getattr(run, "lease_expires_at", None))
        if expires is None:
            return False
        return expires <= now

    def discover(
        self,
        *,
        limit: int = 8,
        now: datetime | None = None,
    ) -> tuple[AsyncResearchCandidate, ...]:
        """Eligible authorized runs, soonest authorization deadline first."""

        if limit <= 0:
            return ()
        moment = now or datetime.now(timezone.utc)
        found: list[AsyncResearchCandidate] = []
        for row in self._candidate_rows(limit):
            run_id = str(row["run_id"])
            run = self.runs.get(run_id)
            if run is None:
                continue
            grant = self.authorizations.get(str(row["authorization_id"]))
            if grant is None:
                # The join promised an active grant; losing it means the run must
                # not be scheduled rather than scheduled on a stale belief.
                continue
            eligible, reason = is_eligible(
                run=run,
                grant=grant,
                lease_available=self._lease_available(run, moment),
                now=moment,
            )
            if not eligible:
                continue
            found.append(
                AsyncResearchCandidate(
                    run_id=run_id,
                    authorization_id=str(grant.id),
                    status=str(getattr(run, "status", "")),
                )
            )
        return tuple(found)

    def claim(
        self,
        run_id: str,
        *,
        holder: str,
        ttl_seconds: int = 90,
        now: datetime | None = None,
    ) -> AsyncResearchClaim:
        """Atomically re-check and take execution rights for one run.

        The discovery result is only a candidate; authority is decided here, in
        one transaction, against the authoritative rows:

        * cancellation is terminal, and a live lease blocks a second worker;
        * the run's own **active** authorization must still be valid (deadline and
          remaining spend), re-read inside the transaction rather than trusted
          from the discovery pass;
        * an unconfirmed paid call (``sent``) blocks new paid work, because a
          database lease cannot revoke a request that already left the process;
        * takeover increments the fencing epoch, so an old worker's identity can
          never be mistaken for current authority.
        """

        if not str(holder).strip():
            raise ClaimRefused("no_holder", "lease holder is required")
        moment = now or datetime.now(timezone.utc)
        ttl = max(5, int(ttl_seconds))
        stamp = moment.isoformat()
        expires = (moment + timedelta(seconds=ttl)).isoformat()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise ClaimRefused("run_missing", f"run not found: {run_id}")
            status = str(row["status"])
            if status == "cancelled":
                connection.rollback()
                raise ClaimRefused("cancelled_is_terminal", f"cancelled run: {run_id}")
            if status not in CANDIDATE_STATUSES:
                connection.rollback()
                raise ClaimRefused(f"status_not_eligible:{status}")
            lease_expiry = _parse_timestamp(row["lease_expires_at"])
            if row["lease_holder"]:
                if lease_expiry is None or lease_expiry > moment:
                    connection.rollback()
                    raise ClaimRefused("lease_held", f"leased by {row['lease_holder']}")

            grant = connection.execute(
                "SELECT * FROM research_authorizations "
                "WHERE run_id = ? AND status = 'active' "
                "ORDER BY authorization_version DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if grant is None:
                connection.rollback()
                raise ClaimRefused("no_active_authorization")
            # 1B-R1/P1: the claim applies the *whole* predicate, not a subset, so a
            # candidate cannot be executed for a reason the discovery pass would have
            # rejected (non-retryable failure, no work left, unexecutable status).
            eligible, ineligible_reason = is_eligible(
                run=_RunView(row),
                grant=_GrantView(grant),  # type: ignore[arg-type]
                lease_available=True,
                now=moment,
            )
            if not eligible:
                connection.rollback()
                raise ClaimRefused(
                    ineligible_reason if ineligible_reason else "not_eligible"
                )
            unconfirmed = connection.execute(
                "SELECT COUNT(*) AS pending FROM llm_spend_ledger "
                "WHERE scope_id = ? AND state = 'sent'",
                (run_id,),
            ).fetchone()
            if unconfirmed is not None and int(unconfirmed["pending"]):
                connection.rollback()
                raise ClaimRefused(
                    "unconfirmed_paid_call",
                    "a paid call's outcome is unknown; refusing to start new paid work",
                )

            epoch = int(row["lease_epoch"] or 0) + 1
            context = _with_operation(
                json.loads(row["research_context"] or "{}"),
                active_operation_id=str(holder),
                active_operation_started_at=stamp,
                stage_started_at=stamp,
            )
            cursor = connection.execute(
                """
                UPDATE web_lookup_runs
                SET status = 'running', lease_epoch = ?, lease_holder = ?,
                    lease_heartbeat_at = ?, lease_expires_at = ?, research_context = ?,
                    updated_at = ?, version = version + 1
                WHERE id = ? AND version = ?
                """,
                (
                    epoch,
                    str(holder),
                    stamp,
                    expires,
                    _dump(context),
                    stamp,
                    run_id,
                    int(row["version"]),
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise ClaimRefused("claim_conflicted", "lease acquisition conflicted")
            connection.commit()
        return AsyncResearchClaim(
            run_id=run_id,
            authorization_id=str(grant["id"]),
            holder=str(holder),
            epoch=epoch,
            expires_at=expires,
        )

    def unconfirmed_calls(self, run_id: str) -> tuple[str, ...]:
        """Paid calls of this **run** whose outcome is still unknown.

        1B-R1: queried by run scope, not by the current authorization id.  A
        re-authorization creates a new grant, so an authorization-scoped query would
        lose sight of a call sent under the previous grant and wrongly unblock it.
        """

        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT call_id FROM llm_spend_ledger "
                "WHERE scope_id = ? AND state = 'sent' ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return tuple(str(row["call_id"]) for row in rows)
