"""Durable user-owned metadata for semantic session navigation."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase

_COMPONENT_NAME = "session_navigation"
_COMPONENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SessionTitleMetadata:
    thread_id: str
    manual_title: str = ""
    updated_at: str = ""
    version: int = 0


class SessionNavigationRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database
        self.database.initialize()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_component_migrations (
                    component TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute(
                "SELECT version FROM runtime_component_migrations WHERE component = ?",
                (_COMPONENT_NAME,),
            ).fetchone()
            current = int(row["version"]) if row else 0
            if current < 1:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_navigation_metadata (
                        thread_id TEXT PRIMARY KEY REFERENCES chat_threads(id),
                        manual_title TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
            connection.execute(
                """
                INSERT OR REPLACE INTO runtime_component_migrations(
                    component, version, applied_at
                ) VALUES (?, ?, ?)
                """,
                (_COMPONENT_NAME, _COMPONENT_SCHEMA_VERSION, utc_now()),
            )
            connection.commit()

    def get_title(self, thread_id: str) -> SessionTitleMetadata:
        with self.database.connect() as connection:
            thread = connection.execute(
                "SELECT id FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if thread is None:
                raise ValueError(f"Chat thread not found: {thread_id}")
            row = connection.execute(
                "SELECT * FROM session_navigation_metadata WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return SessionTitleMetadata(thread_id=thread_id)
        return SessionTitleMetadata(
            thread_id=thread_id,
            manual_title=str(row["manual_title"] or ""),
            updated_at=str(row["updated_at"] or ""),
            version=int(row["version"]),
        )

    def set_manual_title(
        self,
        thread_id: str,
        title: str,
    ) -> SessionTitleMetadata:
        normalized = " ".join(str(title or "").strip().split())[:120]
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            thread = connection.execute(
                "SELECT id FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if thread is None:
                connection.rollback()
                raise ValueError(f"Chat thread not found: {thread_id}")
            existing = connection.execute(
                "SELECT manual_title, version FROM session_navigation_metadata WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            if existing is not None and str(existing["manual_title"] or "") == normalized:
                connection.commit()
                return self.get_title(thread_id)
            next_version = int(existing["version"]) + 1 if existing else 1
            connection.execute(
                """
                INSERT INTO session_navigation_metadata(
                    thread_id, manual_title, updated_at, version
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    manual_title = excluded.manual_title,
                    updated_at = excluded.updated_at,
                    version = excluded.version
                """,
                (thread_id, normalized, now, next_version),
            )
            connection.commit()
        return self.get_title(thread_id)
