"""CL-M3-S1: the append-only settlement audit (contract §12).

The reservation ledger answers one question and answers it forever: *how much
was this run allowed to spend, at most*. This module answers a second, weaker
one: *what did we later learn about each send*. The whole design exists to keep
those two from being confused:

* nothing here updates, refunds or recalculates a reservation. A settlement
  write is an INSERT into its own table and nothing else;
* the table is append-only at the storage layer (triggers in migration 30), and
  this module never issues UPDATE or DELETE against it;
* the current state is the highest ``revision``, so a correction is a new fact
  rather than a rewrite;
* exactly one transition is permitted - ``unresolved -> settled``, once, with
  evidence that names the same request. Everything else is a conflict.

**Idempotency is by content, not by timestamp.** Two callers may report the
same observation at different moments (a retry, two threads closing the same
turn). The second is a no-op when ``(outcome, cost, basis, evidence)`` match;
only a *different* observation is a conflict. Comparing the timestamp would
turn a harmless retry into a fight.

**`settlement_unwritten` is not stored.** A reservation with no observation is
a fact about the *absence* of a row, and it is derived by the recovery scan
(``unwritten``). Writing "we failed to write" would itself be a write that may
fail, and would claim knowledge nobody has.

**Historical reservations are excluded by an epoch.** Migration 30 records the
highest reservation id that existed before the audit layer; those rows were
never expected to have observations, so the scan must not report them as debt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from src.domain.spend_settlement import (
    ALLOWED_TRANSITIONS,
    COST_BASES,
    SETTLEMENT_FAILED,
    SETTLEMENT_OUTCOMES,
    SETTLEMENT_SETTLED,
    SETTLEMENT_UNRESOLVED,
    SettlementEvidenceError,
    parse_evidence,
)

__all__ = [
    "SETTLEMENT_FAILED",
    "SETTLEMENT_SETTLED",
    "SETTLEMENT_UNRESOLVED",
    "SettlementConflict",
    "SettlementError",
    "SettlementIdentityRejected",
    "SettlementRecord",
    "SettlementUnavailable",
    "ReservationRow",
    "SpendSettlementRepository",
]


class SettlementError(RuntimeError):
    """Base class. Every failure here refuses the observation."""


class SettlementUnavailable(SettlementError):
    """The audit store could not be opened, migrated or written."""


class SettlementConflict(SettlementError):
    """A different observation already exists; only the one upgrade may follow."""


class SettlementIdentityRejected(SettlementError):
    """The observation does not name one real reservation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _BusyStore(SettlementError):
    """Internal: SQLite was busy. Retried, then reported as unavailable."""


@dataclass(frozen=True)
class SettlementRecord:
    """One appended observation. ``revision`` 1 is the first fact about a send."""

    experiment_id: str
    request_key: str
    revision: int
    outcome: str
    cost_micros: int | None
    cost_basis: str | None
    evidence_ref: str
    observed_at: str

    @property
    def settled(self) -> bool:
        return self.outcome == SETTLEMENT_SETTLED


@dataclass(frozen=True)
class ReservationRow:
    """The reservation an observation must belong to. Read-only."""

    experiment_id: str
    request_key: str
    amount_micros: int


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError("invalid_observed_at")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("invalid_observed_at") from None
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 400:
        raise ValueError("invalid_identifier")
    return value


def _record(row: sqlite3.Row) -> SettlementRecord:
    return SettlementRecord(
        experiment_id=str(row["experiment_id"]),
        request_key=str(row["request_key"]),
        revision=int(row["revision"]),
        outcome=str(row["outcome"]),
        cost_micros=None if row["cost_micros"] is None else int(row["cost_micros"]),
        cost_basis=None if row["cost_basis"] is None else str(row["cost_basis"]),
        evidence_ref=str(row["evidence_ref"]),
        observed_at=str(row["observed_at"]),
    )


def _same_observation(left: SettlementRecord, right: SettlementRecord) -> bool:
    """Content equality, deliberately excluding the timestamp (see module docstring)."""

    return (
        left.outcome == right.outcome
        and left.cost_micros == right.cost_micros
        and left.cost_basis == right.cost_basis
        and left.evidence_ref == right.evidence_ref
    )


class SpendSettlementRepository:
    """Append observations about real sends. Never touches the money tables."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = 5_000,
        busy_retries: int = 3,
    ) -> None:
        self.database_path = str(Path(database_path).resolve())
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._busy_retries = max(0, int(busy_retries))

    # -- connection ---------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.database_path, timeout=self._busy_timeout_ms / 1000.0
            )
        except sqlite3.Error as exc:  # pragma: no cover - depends on the host
            raise SettlementUnavailable(
                f"settlement store unavailable at {self.database_path}: {exc}"
            ) from exc
        connection.row_factory = sqlite3.Row
        # The foreign key is the storage-level proof that an observation belongs to
        # a real reservation. SQLite defaults it OFF per connection, so it has to be
        # enabled on the same connection that writes - not only in the test helper.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @staticmethod
    def _require_tables(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='llm_spend_settlements'"
        ).fetchone()
        if row is None:
            raise SettlementUnavailable(
                "settlement tables are missing; the runtime database must be "
                "migrated to schema 30"
            )

    # -- validation ---------------------------------------------------------------

    @staticmethod
    def _validate(
        *,
        outcome: object,
        cost_micros: object,
        cost_basis: object,
        evidence_ref: object,
        request_key: str,
    ) -> tuple[str, int | None, str | None, str]:
        if outcome not in SETTLEMENT_OUTCOMES:
            raise ValueError("invalid_outcome")
        if cost_micros is not None and (
            isinstance(cost_micros, bool) or not isinstance(cost_micros, int)
        ):
            raise ValueError("invalid_cost_micros")
        if cost_micros is not None and cost_micros < 0:
            raise ValueError("invalid_cost_micros")
        if cost_basis is not None and cost_basis not in COST_BASES:
            raise ValueError("invalid_cost_basis")
        if (cost_micros is None) != (cost_basis is None):
            # Unknown cost and unknown basis travel together (contract §12.4).
            raise ValueError("invalid_cost_basis")
        reference = "" if evidence_ref is None else evidence_ref
        if outcome in (SETTLEMENT_SETTLED, SETTLEMENT_FAILED):
            # A completion claim and a failure claim both need a receipt that
            # names this send (:12.2); a timeout is neither, and stays unresolved.
            parse_evidence(reference, request_key)
        elif reference:
            # ``unresolved`` may carry a reference, but it must still be this
            # send's; a free-form string is not evidence.
            parse_evidence(reference, request_key)
        return (
            str(outcome),
            cast("int | None", cost_micros),
            cast("str | None", cost_basis),
            str(reference),
        )

    # -- writes -------------------------------------------------------------------

    def settle(
        self,
        experiment_id: str,
        request_key: str,
        *,
        outcome: str,
        cost_micros: int | None = None,
        cost_basis: str | None = None,
        evidence_ref: str = "",
        observed_at: str,
    ) -> SettlementRecord:
        """Append one observation of a send, idempotently and atomically.

        Returns the stored record - the previous one when this call is a replay.
        Raises ``SettlementConflict`` for a different observation, and
        ``SettlementIdentityRejected`` when no reservation of that name exists.
        """

        experiment = _identifier(experiment_id)
        key = _identifier(request_key)
        moment = _timestamp(observed_at)
        validated_outcome, cost, basis, reference = self._validate(
            outcome=outcome,
            cost_micros=cost_micros,
            cost_basis=cost_basis,
            evidence_ref=evidence_ref,
            request_key=key,
        )
        last_error: Exception | None = None
        for attempt in range(self._busy_retries + 1):
            try:
                return self._settle_once(
                    experiment,
                    key,
                    outcome=validated_outcome,
                    cost_micros=cost,
                    cost_basis=basis,
                    evidence_ref=reference,
                    observed_at=moment,
                )
            except _BusyStore as exc:
                last_error = exc
                if attempt >= self._busy_retries:
                    break
        raise SettlementUnavailable(
            f"settlement store stayed busy after {self._busy_retries + 1} "
            f"attempts: {last_error}"
        )

    def _settle_once(
        self,
        experiment_id: str,
        request_key: str,
        *,
        outcome: str,
        cost_micros: int | None,
        cost_basis: str | None,
        evidence_ref: str,
        observed_at: str,
    ) -> SettlementRecord:
        connection = self._connect()
        try:
            self._require_tables(connection)
            # BEGIN IMMEDIATE: read the last revision, check the transition, allocate
            # the next revision and append in one write transaction. "Read then
            # write" in two transactions is the window the contract forbids.
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                "SELECT amount_micros FROM llm_spend_reservations "
                "WHERE experiment_id = ? AND request_key = ?",
                (experiment_id, request_key),
            ).fetchone()
            if reservation is None:
                raise SettlementIdentityRejected("reservation_not_found")
            last_row = connection.execute(
                "SELECT * FROM llm_spend_settlements "
                "WHERE experiment_id = ? AND request_key = ? "
                "ORDER BY revision DESC LIMIT 1",
                (experiment_id, request_key),
            ).fetchone()
            candidate = SettlementRecord(
                experiment_id=experiment_id,
                request_key=request_key,
                revision=1 if last_row is None else int(last_row["revision"]) + 1,
                outcome=outcome,
                cost_micros=cost_micros,
                cost_basis=cost_basis,
                evidence_ref=evidence_ref,
                observed_at=observed_at,
            )
            if last_row is not None:
                previous = _record(last_row)
                if _same_observation(previous, candidate):
                    # A replay. No revision: the fact did not change.
                    connection.commit()
                    return previous
                if (previous.outcome, outcome) not in ALLOWED_TRANSITIONS:
                    raise SettlementConflict(
                        f"cannot move {previous.outcome} -> {outcome} "
                        f"for {experiment_id}/{request_key}"
                    )
            connection.execute(
                "INSERT INTO llm_spend_settlements("
                "experiment_id, request_key, revision, outcome, cost_micros, "
                "cost_basis, evidence_ref, observed_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.experiment_id,
                    candidate.request_key,
                    candidate.revision,
                    candidate.outcome,
                    candidate.cost_micros,
                    candidate.cost_basis,
                    candidate.evidence_ref,
                    candidate.observed_at,
                ),
            )
            connection.commit()
            return candidate
        except SettlementError:
            connection.rollback()
            raise
        except SettlementEvidenceError:
            connection.rollback()
            raise
        except sqlite3.OperationalError as exc:
            connection.rollback()
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise _BusyStore(f"settlement store is busy: {exc}") from exc
            raise SettlementUnavailable(f"settlement write failed: {exc}") from exc
        except sqlite3.IntegrityError as exc:
            # A concurrent writer took this revision between our read and our
            # insert (possible only outside BEGIN IMMEDIATE's lock, or through a
            # second connection bypassing this class). Re-read and decide: an
            # identical observation is still an idempotent success.
            connection.rollback()
            existing = self._current(experiment_id, request_key)
            if existing is not None and _same_observation(
                existing,
                SettlementRecord(
                    experiment_id=experiment_id,
                    request_key=request_key,
                    revision=existing.revision,
                    outcome=outcome,
                    cost_micros=cost_micros,
                    cost_basis=cost_basis,
                    evidence_ref=evidence_ref,
                    observed_at=observed_at,
                ),
            ):
                return existing
            raise SettlementConflict("settlement revision already taken") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise SettlementUnavailable(f"settlement write failed: {exc}") from exc
        finally:
            connection.close()

    # -- reads --------------------------------------------------------------------

    def current(self, experiment_id: str, request_key: str) -> SettlementRecord | None:
        return self._current(_identifier(experiment_id), _identifier(request_key))

    def _current(
        self, experiment_id: str, request_key: str
    ) -> SettlementRecord | None:
        connection = self._connect()
        try:
            self._require_tables(connection)
            row = connection.execute(
                "SELECT * FROM llm_spend_settlements "
                "WHERE experiment_id = ? AND request_key = ? "
                "ORDER BY revision DESC LIMIT 1",
                (experiment_id, request_key),
            ).fetchone()
        finally:
            connection.close()
        return None if row is None else _record(row)

    def history(
        self, experiment_id: str, request_key: str
    ) -> tuple[SettlementRecord, ...]:
        """Every observation, oldest first. The audit trail is the point."""

        connection = self._connect()
        try:
            self._require_tables(connection)
            rows = connection.execute(
                "SELECT * FROM llm_spend_settlements "
                "WHERE experiment_id = ? AND request_key = ? "
                "ORDER BY revision ASC",
                (_identifier(experiment_id), _identifier(request_key)),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_record(row) for row in rows)

    def reservation(
        self, experiment_id: str, request_key: str
    ) -> ReservationRow | None:
        """The reservation this observation would belong to, or ``None``."""

        connection = self._connect()
        try:
            self._require_tables(connection)
            row = connection.execute(
                "SELECT experiment_id, request_key, amount_micros "
                "FROM llm_spend_reservations "
                "WHERE experiment_id = ? AND request_key = ?",
                (_identifier(experiment_id), _identifier(request_key)),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return ReservationRow(
            experiment_id=str(row["experiment_id"]),
            request_key=str(row["request_key"]),
            amount_micros=int(row["amount_micros"]),
        )

    def experiments_for_request(self, request_key: str) -> tuple[str, ...]:
        """Every experiment that reserved this key. More than one is ambiguous."""

        connection = self._connect()
        try:
            self._require_tables(connection)
            rows = connection.execute(
                "SELECT DISTINCT experiment_id FROM llm_spend_reservations "
                "WHERE request_key = ? ORDER BY experiment_id",
                (_identifier(request_key),),
            ).fetchall()
        finally:
            connection.close()
        return tuple(str(row["experiment_id"]) for row in rows)

    def unwritten(
        self, *, experiment_id: str | None = None
    ) -> tuple[tuple[str, str], ...]:
        """Reservations with no observation at all: ``settlement_unwritten``.

        Excludes everything at or below the migration-30 watermark: those rows
        predate the audit layer and were never expected to have an observation.
        """

        query = (
            "SELECT r.experiment_id, r.request_key FROM llm_spend_reservations r "
            "WHERE r.reservation_id > ("
            "  SELECT audited_from_reservation_id FROM llm_spend_settlement_epoch "
            "  WHERE singleton = 1"
            ") AND NOT EXISTS ("
            "  SELECT 1 FROM llm_spend_settlements s "
            "  WHERE s.experiment_id = r.experiment_id "
            "    AND s.request_key = r.request_key"
            ")"
        )
        parameters: tuple[object, ...] = ()
        if experiment_id is not None:
            query += " AND r.experiment_id = ?"
            parameters = (_identifier(experiment_id),)
        query += " ORDER BY r.reservation_id ASC"
        connection = self._connect()
        try:
            self._require_tables(connection)
            rows = connection.execute(query, parameters).fetchall()
        finally:
            connection.close()
        return tuple((str(row["experiment_id"]), str(row["request_key"])) for row in rows)

    def overruns(self, experiment_id: str) -> tuple[ReservationRow, ...]:
        """Sends whose *current* settled cost exceeds the ceiling reserved for it.

        Derived, never stored: the reservation is not edited to fit the
        observation. The adapter refuses further paid calls for such an
        experiment until a human looks at it.
        """

        connection = self._connect()
        try:
            self._require_tables(connection)
            rows = connection.execute(
                "SELECT r.experiment_id, r.request_key, r.amount_micros "
                "FROM llm_spend_reservations r "
                "JOIN llm_spend_settlements s "
                "  ON s.experiment_id = r.experiment_id "
                " AND s.request_key = r.request_key "
                "WHERE r.experiment_id = ? "
                "  AND s.outcome = 'settled' "
                "  AND s.cost_micros IS NOT NULL "
                "  AND s.cost_micros > r.amount_micros "
                "  AND s.revision = ("
                "    SELECT MAX(x.revision) FROM llm_spend_settlements x "
                "    WHERE x.experiment_id = s.experiment_id "
                "      AND x.request_key = s.request_key"
                "  ) "
                "ORDER BY r.reservation_id ASC",
                (_identifier(experiment_id),),
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            ReservationRow(
                experiment_id=str(row["experiment_id"]),
                request_key=str(row["request_key"]),
                amount_micros=int(row["amount_micros"]),
            )
            for row in rows
        )
