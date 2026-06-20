"""SQLite runtime database and ordered schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 2

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE runtime_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE chat_threads (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            settings_snapshot TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE chat_turns (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id),
            user_message TEXT NOT NULL,
            assistant_message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            route_snapshot TEXT NOT NULL DEFAULT '{}',
            rag_snapshot TEXT NOT NULL DEFAULT '{}',
            parent_turn_id TEXT REFERENCES chat_turns(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_chat_turns_thread_created
            ON chat_turns(thread_id, created_at);

        CREATE TABLE group_threads (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            archived_at TEXT,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE group_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES group_threads(id),
            speaker TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_group_messages_thread_created
            ON group_messages(thread_id, created_at);

        CREATE TABLE news_runs (
            id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            safe_mode INTEGER NOT NULL DEFAULT 0,
            items TEXT NOT NULL DEFAULT '[]',
            digest TEXT NOT NULL DEFAULT '',
            warnings TEXT NOT NULL DEFAULT '[]',
            group_thread_id TEXT REFERENCES group_threads(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE tool_runs (
            id TEXT PRIMARY KEY,
            tool_name TEXT NOT NULL,
            args TEXT NOT NULL DEFAULT '{}',
            args_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            preview TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE operations (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            owner_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        ALTER TABLE chat_threads ADD COLUMN archived_at TEXT;
        ALTER TABLE chat_threads ADD COLUMN export_path TEXT NOT NULL DEFAULT '';
        ALTER TABLE chat_turns ADD COLUMN operation_id TEXT;
        ALTER TABLE chat_turns ADD COLUMN conversation_instruction TEXT NOT NULL DEFAULT '';

        CREATE INDEX idx_chat_threads_status_updated
            ON chat_threads(status, updated_at DESC);
        CREATE INDEX idx_chat_turns_operation
            ON chat_turns(operation_id);
        """,
    ),
)


class RuntimeDatabase:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            apply_migrations(connection)


def schema_version(connection: sqlite3.Connection) -> int:
    meta_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runtime_meta'"
    ).fetchone()
    if meta_exists is None:
        return 0
    row = connection.execute(
        "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0]) if row else 0


def apply_migrations(
    connection: sqlite3.Connection,
    *,
    after_statement: Callable[[int, int], None] | None = None,
) -> None:
    _ensure_migration_ledger(connection)
    current = schema_version(connection)
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Runtime database schema {current} is newer than supported {SCHEMA_VERSION}"
        )
    for version, sql in MIGRATIONS:
        try:
            connection.execute("BEGIN IMMEDIATE")
            current = schema_version(connection)
            if version <= current:
                connection.commit()
                continue
            started_at = _utc_now()
            connection.execute(
                """
                INSERT OR REPLACE INTO runtime_migrations(
                    version, status, started_at, completed_at, error
                ) VALUES (?, 'applying', ?, NULL, '')
                """,
                (version, started_at),
            )
            for index, statement in enumerate(_migration_statements(sql)):
                connection.execute(statement)
                if after_statement is not None:
                    after_statement(version, index)
            connection.execute(
                "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES('schema_version', ?)",
                (str(version),),
            )
            connection.execute(
                """
                UPDATE runtime_migrations
                SET status = 'completed', completed_at = ?, error = ''
                WHERE version = ?
                """,
                (_utc_now(), version),
            )
            connection.commit()
            current = version
        except Exception as exc:
            connection.rollback()
            connection.execute(
                """
                INSERT OR REPLACE INTO runtime_migrations(
                    version, status, started_at, completed_at, error
                ) VALUES (?, 'failed', ?, ?, ?)
                """,
                (version, _utc_now(), _utc_now(), str(exc)),
            )
            connection.commit()
            raise


def _ensure_migration_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_migrations (
            version INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    connection.commit()


def _migration_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines():
        buffer = f"{buffer}\n{line}" if buffer else line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise RuntimeError("Migration contains an incomplete SQL statement")
    return statements


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_schema(connection: sqlite3.Connection) -> None:
    """Backward-compatible alias used by older callers and tests."""

    apply_migrations(connection)
