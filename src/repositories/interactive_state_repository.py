"""Host-owned snapshots of where a learner left a generated document."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.domain.runtime_entities import utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase

MAX_STATE_CHARS = 4000


@dataclass(frozen=True)
class InteractiveStateSnapshot:
    thread_id: str
    component_id: str
    revision: int
    state: dict[str, Any]
    updated_at: str


def state_size(state: dict[str, Any]) -> int:
    return len(json.dumps(state, ensure_ascii=False, separators=(",", ":")))


class InteractiveStateRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def thread_exists(self, thread_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
        return row is not None

    def upsert(
        self,
        thread_id: str,
        component_id: str,
        revision: int,
        state: dict[str, Any],
    ) -> InteractiveStateSnapshot:
        if not isinstance(state, dict):
            raise ValueError("state must be a JSON object")
        if state_size(state) > MAX_STATE_CHARS:
            raise ValueError(f"state must be at most {MAX_STATE_CHARS} characters")
        updated_at = utc_now()
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO interactive_state_snapshots "
                "(thread_id, component_id, revision, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(thread_id, component_id, revision) DO UPDATE SET "
                "state_json = excluded.state_json, "
                "updated_at = excluded.updated_at",
                (thread_id, component_id, revision, payload, updated_at),
            )
        return InteractiveStateSnapshot(
            thread_id=thread_id,
            component_id=component_id,
            revision=revision,
            state=state,
            updated_at=updated_at,
        )

    def get(
        self, thread_id: str, component_id: str, revision: int
    ) -> InteractiveStateSnapshot | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT thread_id, component_id, revision, state_json, updated_at "
                "FROM interactive_state_snapshots "
                "WHERE thread_id = ? AND component_id = ? AND revision = ?",
                (thread_id, component_id, revision),
            ).fetchone()
        if row is None:
            return None
        try:
            state = json.loads(row["state_json"])
        except ValueError:
            return None
        if not isinstance(state, dict):
            return None
        return InteractiveStateSnapshot(
            thread_id=row["thread_id"],
            component_id=row["component_id"],
            revision=int(row["revision"]),
            state=state,
            updated_at=row["updated_at"],
        )
