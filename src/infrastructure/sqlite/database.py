"""SQLite runtime database bootstrap for Architecture V2."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


class RuntimeDatabase:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            apply_schema(connection)


def apply_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runtime_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            settings_snapshot TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS chat_turns (
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

        CREATE INDEX IF NOT EXISTS idx_chat_turns_thread_created
            ON chat_turns(thread_id, created_at);

        CREATE TABLE IF NOT EXISTS group_threads (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            archived_at TEXT,
            version INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS group_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES group_threads(id),
            speaker TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_group_messages_thread_created
            ON group_messages(thread_id, created_at);

        CREATE TABLE IF NOT EXISTS news_runs (
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

        CREATE TABLE IF NOT EXISTS tool_runs (
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

        CREATE TABLE IF NOT EXISTS operations (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            owner_id TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
