"""Durable, multi-scope model-send budget.

The money ledger answers "may this call spend?". It cannot answer "may this arm
still send?" because a cheap call fits the money cap long after the send budget
is gone. This module counts *sends* across processes, restart-safely, in the same
``BEGIN IMMEDIATE`` discipline the repository already uses for reservations.

Why a dedicated file instead of ``SqliteDecisionAdmission``: that class owns one
immutable budget per database, while a preview needs three nested scopes
(experiment / arm / round) and must charge each send more than one unit when the
SDK may retry internally. Splitting that into several files would make "the send
is counted everywhere or nowhere" impossible to guarantee; one file with one
transaction does.

There is no refund and no reset API. A failed or unknown upstream attempt keeps
its units, because the alternative is a cap that can be reopened by retrying.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

MAX_REQUEST_KEY_CHARS = 160


class SendBudgetError(RuntimeError):
    """Base class for send-budget failures; callers must fail closed."""


class SendBudgetUnavailable(SendBudgetError):
    """The budget file is missing, foreign, or locked by another writer."""


class SendBudgetConflict(SendBudgetError):
    """A scope would change its cap, or a send key is being reused."""


class SendBudgetExceeded(SendBudgetError):
    """A scope has no room left for this send."""

    def __init__(self, scope: str, used: int, units: int, cap: int) -> None:
        super().__init__(
            f"send budget exhausted for {scope}: used={used} next={units} cap={cap}"
        )
        self.scope = scope
        self.used = used
        self.units = units
        self.cap = cap


_LIMITS_TABLE = "send_budget_limits"
_RESERVATIONS_TABLE = "send_budget_reservations"
_OWNED_TABLES = frozenset({_LIMITS_TABLE, _RESERVATIONS_TABLE})
# The columns each owned table must have. A table with the right name and the
# wrong shape is somebody else's, or an older contract that must not be adopted
# silently: reading it would produce confident, wrong counts.
_REQUIRED_COLUMNS = {
    _LIMITS_TABLE: frozenset({"scope", "cap", "created_at"}),
    _RESERVATIONS_TABLE: frozenset({"scope", "request_key", "units", "reserved_at"}),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


class SendBudget:
    """One SQLite file holding an immutable cap per scope and its send counts."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        if str(path) == ":memory:":
            raise ValueError("a send budget must live in a file")
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._ensure_schema()

    # -- connection ---------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=self._busy_timeout_ms / 1000.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        """Create the schema once, and only ever inside a database we own.

        A path is not a promise. If a caller hands over the runtime database or
        another tool's file, creating two tables in it would both pollute that
        file and turn our counts into a silent second meaning of its contents.
        Ownership is therefore established from the data already there: empty (or
        absent) means ours to initialise, exactly our two tables means ours to
        reopen, anything else is refused.

        The check and the creation share one ``BEGIN IMMEDIATE`` transaction, so
        two processes starting at once cannot both conclude "empty" and then both
        write.
        """

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    existing = self._objects(connection)
                    if existing - _OWNED_TABLES:
                        raise SendBudgetUnavailable(
                            f"{self.path} already holds tables this send budget "
                            f"does not own: {sorted(existing - _OWNED_TABLES)}"
                        )
                    if existing and existing != _OWNED_TABLES:
                        raise SendBudgetUnavailable(
                            f"{self.path} holds a partial send budget "
                            f"({sorted(existing)}); refusing to adopt a ledger "
                            "whose missing half would read as an empty history"
                        )
                    if not existing:
                        self._create(connection)
                    self._verify_schema(connection)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
        except sqlite3.Error as exc:  # busy, locked, or not a database
            raise SendBudgetUnavailable(
                f"send budget {self.path} is unavailable: {exc}"
            ) from exc

    @staticmethod
    def _objects(connection: sqlite3.Connection) -> set[str]:
        """Tables, views and triggers: what carries meaning this code did not write.

        Indexes are excluded on purpose - they are derived from the tables, and
        the index this class creates would otherwise look like a foreign object on
        every reopen.
        """

        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table', 'view', 'trigger') "
                "AND name NOT GLOB 'sqlite_*'"
            )
        }

    @staticmethod
    def _create(connection: sqlite3.Connection) -> None:
        connection.execute(
            f"CREATE TABLE {_LIMITS_TABLE} ("
            "scope TEXT PRIMARY KEY, "
            "cap INTEGER NOT NULL CHECK(cap > 0), "
            "created_at TEXT NOT NULL)"
        )
        connection.execute(
            f"CREATE TABLE {_RESERVATIONS_TABLE} ("
            "scope TEXT NOT NULL, "
            "request_key TEXT NOT NULL, "
            "units INTEGER NOT NULL CHECK(units > 0), "
            "reserved_at TEXT NOT NULL, "
            f"PRIMARY KEY (scope, request_key))"
        )

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        for table, required in _REQUIRED_COLUMNS.items():
            found = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            missing = required - found
            if missing:
                raise SendBudgetUnavailable(
                    f"table {table} in {self.path} is missing {sorted(missing)}; "
                    "refusing to count sends in a schema this code did not define"
                )
        connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{_RESERVATIONS_TABLE}_scope "
            f"ON {_RESERVATIONS_TABLE}(scope)"
        )

    # -- caps ---------------------------------------------------------------
    def register(self, caps: Mapping[str, int]) -> None:
        """Create each scope once; afterwards verify, never widen.

        Re-running with the same caps is idempotent, which is what a restarted
        runner needs. A different cap is a configuration error: honouring it
        would silently reopen a budget a reviewer approved at a fixed number.
        """

        if not caps:
            raise ValueError("at least one send scope is required")
        for scope, cap in caps.items():
            if not isinstance(scope, str) or not scope.strip():
                raise ValueError("send scope names must be non-empty strings")
            _positive_int(cap, f"cap for {scope}")
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for scope, cap in caps.items():
                    row = connection.execute(
                        f"SELECT cap FROM {_LIMITS_TABLE} WHERE scope = ?",
                        (scope,),
                    ).fetchone()
                    if row is None:
                        connection.execute(
                            f"INSERT INTO {_LIMITS_TABLE}(scope, cap, created_at) "
                            "VALUES (?, ?, ?)",
                            (scope, int(cap), _utc_now()),
                        )
                    elif int(row["cap"]) != int(cap):
                        connection.rollback()
                        raise SendBudgetConflict(
                            f"scope {scope} already has cap {int(row['cap'])}, "
                            f"refusing to change it to {int(cap)}"
                        )
                connection.commit()
        except sqlite3.Error as exc:
            raise SendBudgetUnavailable(
                f"send budget {self.path} is unavailable: {exc}"
            ) from exc

    def cap(self, scope: str) -> int | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT cap FROM {_LIMITS_TABLE} WHERE scope = ?", (scope,)
            ).fetchone()
        return None if row is None else int(row["cap"])

    # -- counting -----------------------------------------------------------
    def reserve(
        self,
        request_key: str,
        scopes: Iterable[str],
        *,
        units: int = 1,
    ) -> None:
        """Charge ``units`` to every scope, or to none of them.

        One transaction, one decision: two processes racing for the last unit
        cannot both win, and a refusal never leaves a partial charge behind.
        """

        if (
            not isinstance(request_key, str)
            or not request_key.strip()
            or len(request_key) > MAX_REQUEST_KEY_CHARS
        ):
            raise ValueError("invalid send request key")
        _positive_int(units, "units")
        ordered = list(dict.fromkeys(scopes))
        if not ordered:
            raise ValueError("at least one send scope is required")

        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                caps: dict[str, int] = {}
                for scope in ordered:
                    row = connection.execute(
                        f"SELECT cap FROM {_LIMITS_TABLE} WHERE scope = ?",
                        (scope,),
                    ).fetchone()
                    if row is None:
                        connection.rollback()
                        raise SendBudgetUnavailable(
                            f"send scope {scope} has no registered cap"
                        )
                    caps[scope] = int(row["cap"])

                for scope in ordered:
                    if connection.execute(
                        f"SELECT 1 FROM {_RESERVATIONS_TABLE} "
                        "WHERE scope = ? AND request_key = ?",
                        (scope, request_key),
                    ).fetchone():
                        connection.rollback()
                        raise SendBudgetConflict(
                            f"send key {request_key!r} is already counted in "
                            f"{scope}; a new send needs a new key"
                        )

                now = _utc_now()
                for scope in ordered:
                    used = int(
                        connection.execute(
                            f"SELECT COALESCE(SUM(units), 0) FROM "
                            f"{_RESERVATIONS_TABLE} WHERE scope = ?",
                            (scope,),
                        ).fetchone()[0]
                    )
                    cap = caps[scope]
                    if used + int(units) > cap:
                        connection.rollback()
                        raise SendBudgetExceeded(scope, used, int(units), cap)

                for scope in ordered:
                    connection.execute(
                        f"INSERT INTO {_RESERVATIONS_TABLE}"
                        "(scope, request_key, units, reserved_at) VALUES (?, ?, ?, ?)",
                        (scope, request_key, int(units), now),
                    )
                connection.commit()
        except sqlite3.Error as exc:
            raise SendBudgetUnavailable(
                f"send budget {self.path} is unavailable: {exc}"
            ) from exc

    def usage(self, scope: str) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT COALESCE(SUM(units), 0) FROM {_RESERVATIONS_TABLE} "
                "WHERE scope = ?",
                (scope,),
            ).fetchone()
        return int(row[0])

    def remaining(self, scope: str) -> int:
        cap = self.cap(scope)
        if cap is None:
            raise SendBudgetUnavailable(f"send scope {scope} has no registered cap")
        return max(0, cap - self.usage(scope))


__all__ = [
    "SendBudget",
    "SendBudgetConflict",
    "SendBudgetError",
    "SendBudgetExceeded",
    "SendBudgetUnavailable",
]
