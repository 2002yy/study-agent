"""Durable, cross-process reservation ledger for paid model calls.

The process-global counter in :mod:`src.llm_spend_guard` cannot be the only
ledger for an acceptance experiment: a restart forgets everything, and two
processes would each believe they own the whole budget. This module keeps the
authority in the runtime SQLite database, where it survives restarts and is
shared by every process that opens the same absolute path.

Rules that the storage itself enforces:

* **money is integer micro-CNY** (1 CNY = 1_000_000 micro-CNY); no float balance
  is ever compared, so the boundary cannot drift;
* the experiment's ``cap_micros`` is written once and is **immutable** - a later
  process cannot widen it through the environment, and a different pricing
  configuration is detected instead of silently reusing possibly cheaper prices;
* a reservation is inserted inside ``BEGIN IMMEDIATE`` after reading the current
  total, so two processes cannot both pass the same boundary;
* reservations are **never refunded**, so the cap bounds the reserved cost even
  across crashes;
* a ``request_key`` may be reserved **once**. Presenting it again is refused
  rather than treated as a free replay: a request that was already sent may have
  cost money, and the cap must not be evaded by re-using its key.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

MICROS_PER_CNY = 1_000_000


class SpendLedgerError(RuntimeError):
    """Base class for ledger failures. Every one of them refuses the call."""


class SpendLedgerUnavailable(SpendLedgerError):
    """The ledger could not be opened, migrated or written."""


class SpendCapExceeded(SpendLedgerError):
    """The reservation would take the experiment past its durable cap."""


class SpendLedgerConflict(SpendLedgerError):
    """The request re-used a key with a different identity, model or amount."""


class SpendAdmissionRefused(SpendLedgerError):
    """A guard inside the reservation transaction refused this send.

    Distinct from ``SpendCapExceeded``: the cap is a rule the ledger owns, while
    this reason comes from an observation the ledger only reports. The caller
    needs to tell "the budget is full" from "the budget was proven wrong".
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# A guard runs inside the write transaction with the connection that is about to
# insert the reservation. It returns a refusal reason, or ``None`` to admit.
AdmissionGuard = Callable[[sqlite3.Connection, str], str | None]


class _BusyDatabase(SpendLedgerError):
    """Internal: SQLite was busy. Retried, then reported as unavailable.

    Raised distinctly so the retry loop can actually see it - wrapping it as
    ``SpendLedgerUnavailable`` first would make the retries dead code.
    """


def cny_to_micros(value: float) -> int:
    """Round a CNY amount up to whole micro-CNY (never down: never undercharge)."""

    scaled = float(value) * MICROS_PER_CNY
    whole = int(scaled)
    return whole if scaled == whole else whole + 1


def request_fingerprint(
    *,
    amount_micros: int,
    model: str,
    purpose: str,
    identity: str,
) -> str:
    payload = json.dumps(
        {
            "amount_micros": int(amount_micros),
            "model": str(model),
            "purpose": str(purpose),
            "identity": str(identity),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExperimentBudget:
    experiment_id: str
    cap_micros: int
    pricing_fingerprint: str
    created_at: str


@dataclass(frozen=True)
class Reservation:
    experiment_id: str
    request_key: str
    amount_micros: int
    reserved_total_micros: int
    cap_micros: int

    @property
    def remaining_micros(self) -> int:
        return max(0, self.cap_micros - self.reserved_total_micros)


@dataclass(frozen=True)
class ReservedSend:
    """One committed reservation, as the ledger stored it.

    The authorization is issued from this row, not from the caller's claims: a
    signature over numbers nobody checked would prove only that the signer can
    compute an HMAC.
    """

    experiment_id: str
    request_key: str
    amount_micros: int
    model: str
    purpose: str
    identity: str


class SpendLedger:
    """SQLite-backed reservation ledger. One instance per database path."""

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

    # -- connection ---------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                self.database_path, timeout=self._busy_timeout_ms / 1000.0
            )
        except sqlite3.Error as exc:  # pragma: no cover - depends on the host
            raise SpendLedgerUnavailable(
                f"spend ledger unavailable at {self.database_path}: {exc}"
            ) from exc
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @staticmethod
    def _require_tables(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'llm_spend_reservations'
            """
        ).fetchone()
        if row is None:
            raise SpendLedgerUnavailable(
                "spend ledger tables are missing; the runtime database must be "
                "migrated to the schema that defines them"
            )

    # -- experiment ---------------------------------------------------------
    def ensure_experiment(
        self,
        experiment_id: str,
        *,
        cap_micros: int,
        pricing_fingerprint: str,
        now: str,
    ) -> ExperimentBudget:
        """Create the experiment once; afterwards verify, never adjust.

        A second process that configured a larger cap or different prices is a
        configuration error, not an upgrade: honouring it would silently widen a
        budget that a reviewer approved at a fixed amount.
        """

        if not experiment_id:
            raise SpendLedgerError("experiment_id is required")
        if cap_micros <= 0:
            raise SpendLedgerError("experiment cap must be positive")
        connection = self._connect()
        try:
            self._require_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM llm_spend_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO llm_spend_experiments(
                        experiment_id, cap_micros, pricing_fingerprint, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (experiment_id, int(cap_micros), pricing_fingerprint, now),
                )
                connection.commit()
                return ExperimentBudget(
                    experiment_id=experiment_id,
                    cap_micros=int(cap_micros),
                    pricing_fingerprint=pricing_fingerprint,
                    created_at=now,
                )
            connection.commit()
            stored_cap = int(row["cap_micros"])
            stored_pricing = str(row["pricing_fingerprint"])
            if stored_cap != int(cap_micros):
                raise SpendLedgerConflict(
                    f"experiment {experiment_id} is capped at {stored_cap} micro-CNY; "
                    f"this process configured {int(cap_micros)} and cannot change it"
                )
            if stored_pricing != pricing_fingerprint:
                raise SpendLedgerConflict(
                    f"experiment {experiment_id} was created with a different pricing "
                    "configuration; refusing to reuse it under new prices"
                )
            return ExperimentBudget(
                experiment_id=experiment_id,
                cap_micros=stored_cap,
                pricing_fingerprint=stored_pricing,
                created_at=str(row["created_at"]),
            )
        except SpendLedgerError:
            connection.rollback()
            raise
        except sqlite3.OperationalError as exc:
            connection.rollback()
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise _BusyDatabase(f"spend ledger is busy: {exc}") from exc
            raise SpendLedgerUnavailable(f"spend ledger write failed: {exc}") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise SpendLedgerUnavailable(f"spend ledger write failed: {exc}") from exc
        finally:
            connection.close()

    # -- reservation --------------------------------------------------------
    def reserve(
        self,
        experiment_id: str,
        *,
        request_key: str,
        amount_micros: int,
        purpose: str,
        model: str,
        identity: str,
        now: str,
        admission_guard: AdmissionGuard | None = None,
    ) -> Reservation:
        """Atomically reserve ``amount_micros`` for one paid call.

        ``request_key`` names one actual send. It must be unique per send: a
        retry of a request that was already issued is a *new* send and must carry
        a new key, because the first one may already have been billed. Presenting
        a key twice is refused, so a retry can neither borrow a reservation nor
        hide a second charge behind the first one.

        ``admission_guard`` runs **inside** the same write transaction that
        inserts the reservation. A guard evaluated before the transaction is a
        guess: an observation committed between the check and the insert is
        invisible to it, and the reservation is written anyway. Passing it here
        is what makes the check and the write one decision.
        """

        if not request_key:
            raise SpendLedgerError("request_key is required")
        if amount_micros < 0:
            raise SpendLedgerError("reservation amount must not be negative")
        fingerprint = request_fingerprint(
            amount_micros=amount_micros,
            model=model,
            purpose=purpose,
            identity=identity,
        )
        last_error: Exception | None = None
        for attempt in range(self._busy_retries + 1):  # a busy database is retried
            try:
                return self._reserve_once(
                    experiment_id,
                    request_key=request_key,
                    amount_micros=int(amount_micros),
                    purpose=purpose,
                    model=model,
                    identity=identity,
                    fingerprint=fingerprint,
                    now=now,
                    admission_guard=admission_guard,
                )
            except _BusyDatabase as exc:
                last_error = exc
                if attempt >= self._busy_retries:
                    break
        raise SpendLedgerUnavailable(
            f"spend ledger stayed busy after {self._busy_retries + 1} attempts: {last_error}"
        )

    def _reserve_once(
        self,
        experiment_id: str,
        *,
        request_key: str,
        amount_micros: int,
        purpose: str,
        model: str,
        identity: str,
        fingerprint: str,
        now: str,
        admission_guard: AdmissionGuard | None = None,
    ) -> Reservation:
        connection = self._connect()
        try:
            self._require_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            experiment = connection.execute(
                "SELECT * FROM llm_spend_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if experiment is None:
                raise SpendLedgerError(
                    f"experiment {experiment_id} has no durable budget; "
                    "the ledger refuses to guess one"
                )
            cap_micros = int(experiment["cap_micros"])
            existing = connection.execute(
                """
                SELECT * FROM llm_spend_reservations
                WHERE experiment_id = ? AND request_key = ?
                """,
                (experiment_id, request_key),
            ).fetchone()
            reserved_total = int(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(amount_micros), 0) FROM llm_spend_reservations
                    WHERE experiment_id = ?
                    """,
                    (experiment_id,),
                ).fetchone()[0]
            )
            if existing is not None:
                connection.commit()
                if str(existing["request_fingerprint"]) != fingerprint:
                    raise SpendLedgerConflict(
                        f"request_key {request_key!r} was already reserved with a "
                        "different request identity, model or amount"
                    )
                raise SpendLedgerConflict(
                    f"request_key {request_key!r} was already reserved for this "
                    "experiment; a new send needs a new key so its cost is counted"
                )
            if reserved_total + amount_micros > cap_micros:
                connection.rollback()
                raise SpendCapExceeded(
                    f"experiment {experiment_id} would exceed its cap: "
                    f"reserved={reserved_total} next={amount_micros} cap={cap_micros} micro-CNY"
                )
            if admission_guard is not None:
                # Inside BEGIN IMMEDIATE, on this connection: an observation that
                # commits after this read is serialised after this write, so the
                # check and the insert cannot disagree about what was known.
                reason = admission_guard(connection, experiment_id)
                if reason:
                    connection.rollback()
                    raise SpendAdmissionRefused(str(reason))
            connection.execute(
                """
                INSERT INTO llm_spend_reservations(
                    experiment_id, request_key, request_fingerprint, purpose, model,
                    identity, amount_micros, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    request_key,
                    fingerprint,
                    str(purpose or ""),
                    str(model or ""),
                    str(identity or ""),
                    amount_micros,
                    now,
                ),
            )
            connection.commit()
            return Reservation(
                experiment_id=experiment_id,
                request_key=request_key,
                amount_micros=amount_micros,
                reserved_total_micros=reserved_total + amount_micros,
                cap_micros=cap_micros,
            )
        except SpendLedgerError:
            connection.rollback()
            raise
        except sqlite3.OperationalError as exc:
            # Lock contention must reach reserve()'s retry loop; wrapping it here
            # first would make those retries dead code.
            connection.rollback()
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise _BusyDatabase(f"spend ledger is busy: {exc}") from exc
            raise SpendLedgerUnavailable(f"spend ledger write failed: {exc}") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise SpendLedgerUnavailable(f"spend ledger write failed: {exc}") from exc
        finally:
            connection.close()

    def experiment_budget(self, experiment_id: str) -> ExperimentBudget | None:
        """The stored budget, including the prices it was created under."""

        connection = self._connect()
        try:
            self._require_tables(connection)
            row = connection.execute(
                "SELECT * FROM llm_spend_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return ExperimentBudget(
            experiment_id=str(row["experiment_id"]),
            cap_micros=int(row["cap_micros"]),
            pricing_fingerprint=str(row["pricing_fingerprint"]),
            created_at=str(row["created_at"]),
        )

    # -- reporting ----------------------------------------------------------
    def reserved_send(
        self, experiment_id: str, request_key: str
    ) -> ReservedSend | None:
        """Read the committed reservation for one send, or ``None``.

        Read-only, and deliberately exact: this is what a send authorization is
        allowed to be based on.
        """

        connection = self._connect()
        try:
            self._require_tables(connection)
            row = connection.execute(
                "SELECT experiment_id, request_key, amount_micros, model, purpose, "
                "identity FROM llm_spend_reservations "
                "WHERE experiment_id = ? AND request_key = ?",
                (experiment_id, request_key),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return ReservedSend(
            experiment_id=str(row["experiment_id"]),
            request_key=str(row["request_key"]),
            amount_micros=int(row["amount_micros"]),
            model=str(row["model"]),
            purpose=str(row["purpose"]),
            identity=str(row["identity"]),
        )

    def experiment_spend(self, experiment_id: str) -> dict[str, int]:
        """Read-only totals for acceptance evidence (no reset, ever)."""

        connection = self._connect()
        try:
            self._require_tables(connection)
            experiment = connection.execute(
                "SELECT * FROM llm_spend_experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
            if experiment is None:
                raise SpendLedgerError(f"unknown experiment {experiment_id}")
            row = connection.execute(
                """
                SELECT COALESCE(SUM(amount_micros), 0) AS reserved,
                       COUNT(*) AS calls
                FROM llm_spend_reservations WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).fetchone()
            cap_micros = int(experiment["cap_micros"])
            reserved = int(row["reserved"])
            return {
                "cap_micros": cap_micros,
                "reserved_micros": reserved,
                "remaining_micros": max(0, cap_micros - reserved),
                "calls": int(row["calls"]),
            }
        finally:
            connection.close()
