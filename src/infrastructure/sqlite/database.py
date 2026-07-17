"""SQLite runtime database and ordered schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA_VERSION = 16

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
    (
        3,
        """
        ALTER TABLE chat_threads ADD COLUMN active_operation_id TEXT;
        ALTER TABLE chat_threads ADD COLUMN active_operation_started_at TEXT;
        ALTER TABLE chat_threads ADD COLUMN archive_operation_id TEXT;
        ALTER TABLE chat_threads ADD COLUMN archive_started_at TEXT;

        UPDATE chat_turns
        SET status = 'interrupted'
        WHERE status IN ('pending', 'streaming');

        UPDATE chat_threads
        SET status = 'active'
        WHERE status = 'archiving';

        CREATE INDEX idx_chat_threads_active_operation
            ON chat_threads(active_operation_id);
        CREATE INDEX idx_chat_threads_archive_operation
            ON chat_threads(archive_operation_id);
        """,
    ),
    (
        4,
        """
        ALTER TABLE group_threads ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';
        ALTER TABLE group_threads ADD COLUMN settings_snapshot TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE group_threads ADD COLUMN active_operation_id TEXT;
        ALTER TABLE group_threads ADD COLUMN active_operation_started_at TEXT;
        ALTER TABLE group_threads ADD COLUMN unread_count INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE group_threads ADD COLUMN archive_operation_id TEXT;
        ALTER TABLE group_threads ADD COLUMN archive_started_at TEXT;
        ALTER TABLE group_threads ADD COLUMN export_path TEXT NOT NULL DEFAULT '';

        ALTER TABLE group_messages ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';
        ALTER TABLE group_messages ADD COLUMN message_type TEXT NOT NULL DEFAULT 'chat';
        ALTER TABLE group_messages ADD COLUMN operation_id TEXT;
        ALTER TABLE group_messages ADD COLUMN error TEXT NOT NULL DEFAULT '';

        UPDATE group_threads SET updated_at = created_at WHERE updated_at = '';
        UPDATE group_messages SET updated_at = created_at WHERE updated_at = '';

        CREATE INDEX idx_group_threads_status_updated
            ON group_threads(status, updated_at DESC);
        CREATE INDEX idx_group_threads_active_operation
            ON group_threads(active_operation_id);
        CREATE INDEX idx_group_threads_archive_operation
            ON group_threads(archive_operation_id);
        CREATE INDEX idx_group_messages_operation
            ON group_messages(operation_id);
        """,
    ),
    (
        5,
        """
        ALTER TABLE group_threads ADD COLUMN last_read_message_id TEXT;

        CREATE INDEX idx_group_messages_thread_status
            ON group_messages(thread_id, status);
        """,
    ),
    (
        6,
        """
        ALTER TABLE news_runs ADD COLUMN source_block TEXT NOT NULL DEFAULT '';
        ALTER TABLE news_runs ADD COLUMN article_coverage TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE news_runs ADD COLUMN discussion TEXT NOT NULL DEFAULT '';
        ALTER TABLE news_runs ADD COLUMN error TEXT NOT NULL DEFAULT '';
        ALTER TABLE news_runs ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE news_runs ADD COLUMN active_operation_id TEXT;
        ALTER TABLE news_runs ADD COLUMN active_operation_started_at TEXT;
        ALTER TABLE news_runs ADD COLUMN stage_started_at TEXT;
        ALTER TABLE news_runs ADD COLUMN completed_at TEXT;

        CREATE INDEX idx_news_runs_stage_updated
            ON news_runs(stage, updated_at DESC);
        CREATE INDEX idx_news_runs_active_operation
            ON news_runs(active_operation_id);
        """,
    ),
    (
        7,
        """
        ALTER TABLE tool_runs ADD COLUMN reason TEXT NOT NULL DEFAULT '';
        ALTER TABLE tool_runs ADD COLUMN elapsed_ms INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE tool_runs ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE tool_runs ADD COLUMN active_operation_id TEXT;
        ALTER TABLE tool_runs ADD COLUMN active_operation_started_at TEXT;
        ALTER TABLE tool_runs ADD COLUMN previewed_at TEXT;
        ALTER TABLE tool_runs ADD COLUMN completed_at TEXT;

        CREATE INDEX idx_tool_runs_status_updated
            ON tool_runs(status, updated_at DESC);
        CREATE INDEX idx_tool_runs_active_operation
            ON tool_runs(active_operation_id);
        """,
    ),
    (
        8,
        """
        ALTER TABLE chat_threads
            ADD COLUMN learning_state TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE chat_turns
            ADD COLUMN pedagogy_snapshot TEXT NOT NULL DEFAULT '{}';
        """,
    ),
    (
        9,
        """
        CREATE TABLE web_lookup_runs (
            id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            status TEXT NOT NULL,
            items TEXT NOT NULL DEFAULT '[]',
            source_block TEXT NOT NULL DEFAULT '',
            warnings TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE INDEX idx_web_lookup_runs_status_updated
            ON web_lookup_runs(status, updated_at DESC);
        """,
    ),
    (
        10,
        """
        CREATE TABLE memory_runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updates TEXT NOT NULL DEFAULT '[]',
            updates_hash TEXT NOT NULL,
            preview TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL DEFAULT '',
            active_operation_id TEXT,
            active_operation_started_at TEXT,
            previewed_at TEXT,
            completed_at TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_memory_runs_status_updated
            ON memory_runs(status, updated_at DESC);
        CREATE INDEX idx_memory_runs_active_operation
            ON memory_runs(active_operation_id);
        """,
    ),
    (
        11,
        """
        CREATE TABLE rag_runs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            request TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            index_version INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE INDEX idx_rag_runs_kind_updated
            ON rag_runs(kind, updated_at DESC);
        CREATE INDEX idx_rag_runs_status_updated
            ON rag_runs(status, updated_at DESC);
        """,
    ),
    (
        12,
        """
        CREATE TABLE rag_index_states (
            index_path TEXT PRIMARY KEY,
            active_version INTEGER NOT NULL DEFAULT 0,
            staging_version INTEGER,
            status TEXT NOT NULL DEFAULT 'idle',
            document_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_rag_index_states_status
            ON rag_index_states(status, updated_at DESC);
        """,
    ),
    (
        13,
        """
        CREATE TABLE pedagogy_eval_runs (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES chat_threads(id),
            turn_id TEXT NOT NULL UNIQUE REFERENCES chat_turns(id),
            learner_input TEXT NOT NULL,
            objective TEXT NOT NULL DEFAULT '',
            protocol TEXT NOT NULL DEFAULT '',
            expected_concepts TEXT NOT NULL DEFAULT '[]',
            evidence TEXT NOT NULL DEFAULT '[]',
            deterministic_result TEXT NOT NULL DEFAULT '{}',
            semantic_result TEXT,
            confidence REAL NOT NULL DEFAULT 0,
            final_decision TEXT NOT NULL,
            reasons TEXT NOT NULL DEFAULT '[]',
            evaluator_version TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_pedagogy_eval_runs_thread_created
            ON pedagogy_eval_runs(thread_id, created_at DESC);
        CREATE INDEX idx_pedagogy_eval_runs_decision
            ON pedagogy_eval_runs(final_decision, created_at DESC);
        """,
    ),
    (
        14,
        """
        ALTER TABLE web_lookup_runs
            ADD COLUMN stage TEXT NOT NULL DEFAULT 'created';
        ALTER TABLE web_lookup_runs
            ADD COLUMN research_context TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE web_lookup_runs
            ADD COLUMN query_attempts TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE web_lookup_runs
            ADD COLUMN selected_sources TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE web_lookup_runs
            ADD COLUMN rejected_sources TEXT NOT NULL DEFAULT '[]';
        ALTER TABLE web_lookup_runs
            ADD COLUMN provider_status TEXT NOT NULL DEFAULT '';
        ALTER TABLE web_lookup_runs
            ADD COLUMN stop_reason TEXT NOT NULL DEFAULT '';
        ALTER TABLE web_lookup_runs
            ADD COLUMN answer_confidence TEXT NOT NULL DEFAULT '';

        UPDATE web_lookup_runs
        SET stage = CASE status
            WHEN 'completed' THEN 'completed'
            WHEN 'failed' THEN 'failed'
            ELSE 'created'
        END;

        UPDATE web_lookup_runs
        SET selected_sources = items
        WHERE status = 'completed' AND items <> '[]';

        UPDATE web_lookup_runs
        SET provider_status = CASE
            WHEN status = 'failed' THEN 'provider_failed'
            WHEN items = '[]' THEN 'empty'
            ELSE 'found'
        END;

        UPDATE web_lookup_runs
        SET stop_reason = CASE
            WHEN status = 'failed' THEN 'providers_failed'
            WHEN items = '[]' THEN 'providers_returned_no_results'
            ELSE 'direct_results_found'
        END;

        CREATE INDEX idx_web_lookup_runs_stage_updated
            ON web_lookup_runs(stage, updated_at DESC);
        """,
    ),
    (
        15,
        """
        UPDATE web_lookup_runs
        SET stage = 'failed',
            status = 'failed',
            provider_status = 'unknown',
            stop_reason = 'legacy_run_interrupted',
            error = CASE
                WHEN error = '' THEN 'Web lookup was interrupted before staged recovery was available'
                ELSE error
            END,
            completed_at = COALESCE(completed_at, updated_at),
            version = version + 1
        WHERE status = 'running';
        """,
    ),
    (
        16,
        """
        CREATE TABLE provider_cache_entries (
            cache_key TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            kind TEXT NOT NULL,
            repository TEXT NOT NULL,
            payload TEXT NOT NULL,
            immutable_refs TEXT NOT NULL DEFAULT '{}',
            provider_status TEXT NOT NULL DEFAULT '',
            budget TEXT NOT NULL DEFAULT '{}',
            reuse_class TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_provider_cache_repository_kind_expiry
            ON provider_cache_entries(repository, kind, expires_at);
        CREATE INDEX idx_provider_cache_expiry
            ON provider_cache_entries(expires_at);
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
