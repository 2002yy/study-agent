"""Restart-safe, conservative call/token admission in an explicitly owned DB.

This standalone ledger never opens the application's runtime database or stores
prompts, model responses or credentials. There is no refund/reset API: failed or
unknown upstream attempts retain their reservations. It is not a currency ledger.
"""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
from typing import Iterator


@dataclass(frozen=True)
class DecisionUsage:
    calls: int
    prompt_chars: int
    output_tokens: int


_TABLES = {"decision_admission_limits", "decision_admission_calls"}


class SqliteDecisionAdmission:
    """One immutable budget per dedicated file, shared across processes.

    Existing foreign databases and budget changes are rejected before writes.
    SQLite contention is bounded; callers must fail closed if admission fails.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_calls: int,
        max_prompt_chars: int,
        max_output_tokens: int,
    ) -> None:
        self._caps = (max_calls, max_prompt_chars, max_output_tokens)
        for value in self._caps:
            _nonnegative_integer(value)
        if str(path) == ":memory:":
            raise ValueError("persistent admission requires a file")
        self._path = path.resolve()
        created = False
        try:
            handle = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # Inspect existing files read-only before taking any write lock.
            # Even a pre-created zero-byte database belongs to somebody else
            # unless it already carries our complete ownership contract.
            with closing(
                sqlite3.connect(self._path.as_uri() + "?mode=ro", uri=True, timeout=0.1)
            ) as existing:
                if self._objects(existing) != _TABLES:
                    raise ValueError(
                        "existing database lacks admission ownership marker"
                    )
                self._verify_limits(existing)
        else:
            os.close(handle)
            created = True
        with self._transaction() as db:
            tables = self._objects(db)
            if tables and tables != _TABLES:
                raise ValueError("admission requires its own database")
            if not tables:
                if not created:
                    raise ValueError(
                        "existing database lost admission ownership marker"
                    )
                db.execute(
                    "CREATE TABLE decision_admission_limits ("
                    "id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, "
                    "max_calls INTEGER NOT NULL, max_prompt_chars INTEGER NOT NULL, "
                    "max_output_tokens INTEGER NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE decision_admission_calls ("
                    "request_id TEXT PRIMARY KEY, prompt_chars INTEGER NOT NULL, "
                    "output_tokens INTEGER NOT NULL, reserved_at TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO decision_admission_limits VALUES (1, 1, ?, ?, ?)",
                    self._caps,
                )
            self._verify_limits(db)

    @staticmethod
    def _objects(db: sqlite3.Connection) -> set[str]:
        return {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            )
        }

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(
            sqlite3.connect(self._path, timeout=0.1, isolation_level=None)
        ) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _verify_limits(self, db: sqlite3.Connection) -> None:
        stored = db.execute(
            "SELECT version, max_calls, max_prompt_chars, max_output_tokens "
            "FROM decision_admission_limits WHERE id=1"
        ).fetchone()
        if stored != (1, *self._caps):
            raise ValueError(
                "admission budget or schema differs from persisted contract"
            )

    @staticmethod
    def _usage(db: sqlite3.Connection) -> DecisionUsage:
        row = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(prompt_chars), 0), "
            "COALESCE(SUM(output_tokens), 0) FROM decision_admission_calls"
        ).fetchone()
        return DecisionUsage(*row)

    def usage(self) -> DecisionUsage:
        with closing(sqlite3.connect(self._path, timeout=0.1)) as db:
            self._verify_limits(db)
            return self._usage(db)

    def reserve(self, request_id: str, prompt_chars: int, output_tokens: int) -> str:
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 160
        ):
            raise ValueError("invalid decision request id")
        _nonnegative_integer(prompt_chars)
        _nonnegative_integer(output_tokens)
        with self._transaction() as db:
            self._verify_limits(db)
            if db.execute(
                "SELECT 1 FROM decision_admission_calls WHERE request_id=?",
                (request_id,),
            ).fetchone():
                return "already_attempted"
            used = self._usage(db)
            if (
                used.calls >= self._caps[0]
                or used.prompt_chars + prompt_chars > self._caps[1]
                or used.output_tokens + output_tokens > self._caps[2]
            ):
                return "budget_exhausted"
            db.execute(
                "INSERT INTO decision_admission_calls VALUES (?, ?, ?, ?)",
                (
                    request_id,
                    prompt_chars,
                    output_tokens,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return "reserved"


def _nonnegative_integer(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("admission requires nonnegative SQLite integers")
