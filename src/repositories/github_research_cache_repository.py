"""Durable GitHub research cache stored in the existing SQLite RAG run table.

The cache deliberately reuses ``rag_runs`` instead of creating a second runtime
truth. Cache rows carry their own schema version, stable canonical key, TTL, and
complete/partial status. Failed provider results are never persisted as reusable
cache entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from src.infrastructure.sqlite.database import RuntimeDatabase

CACHE_RUN_KIND = "github_research_cache"
DEFAULT_SCHEMA_VERSION = 1


def _dump(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _load_object(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_cache_key(
    cache_kind: str,
    identity: dict[str, Any],
    *,
    schema_version: int = DEFAULT_SCHEMA_VERSION,
) -> str:
    canonical = _dump(
        {
            "cache_kind": str(cache_kind or ""),
            "identity": identity,
            "schema_version": int(schema_version),
        }
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"ghrc:v{int(schema_version)}:{str(cache_kind or 'unknown')}:{digest}"


def _row_id(cache_key: str) -> str:
    digest = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()
    return f"ghcache_{digest}"


@dataclass(frozen=True)
class GitHubResearchCacheEntry:
    cache_key: str
    cache_kind: str
    repository: str
    identity: dict[str, Any]
    payload: dict[str, Any]
    cache_status: str
    schema_version: int
    created_at: str
    updated_at: str
    expires_at: str
    size_bytes: int

    @property
    def expired(self) -> bool:
        expires_at = _timestamp(self.expires_at)
        return expires_at is None or expires_at <= _utc_now()


class GitHubResearchCacheRepository:
    """SQLite-backed cache with explicit reuse and cleanup policy."""

    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database
        self.database.initialize()

    def get(
        self,
        cache_kind: str,
        identity: dict[str, Any],
        *,
        schema_version: int = DEFAULT_SCHEMA_VERSION,
        allow_partial: bool = False,
    ) -> GitHubResearchCacheEntry | None:
        cache_key = stable_cache_key(
            cache_kind,
            identity,
            schema_version=schema_version,
        )
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM rag_runs WHERE id = ? AND kind = ?",
                (_row_id(cache_key), CACHE_RUN_KIND),
            ).fetchone()
        if row is None:
            return None
        entry = self._entry_from_row(row)
        if entry is None:
            return None
        if entry.cache_key != cache_key or entry.schema_version != schema_version:
            return None
        if entry.expired:
            self.delete_key(cache_key)
            return None
        if entry.cache_status == "partial" and not allow_partial:
            return None
        if entry.cache_status != "complete" and not (
            allow_partial and entry.cache_status == "partial"
        ):
            return None
        return entry

    def put(
        self,
        cache_kind: str,
        repository: str,
        identity: dict[str, Any],
        payload: dict[str, Any],
        *,
        ttl_seconds: int,
        schema_version: int = DEFAULT_SCHEMA_VERSION,
    ) -> GitHubResearchCacheEntry | None:
        if payload.get("ok") is not True:
            return None
        cache_status = (
            "partial"
            if str(payload.get("provider_status") or "") == "partial"
            else "complete"
        )
        now = _utc_now()
        expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
        cache_key = stable_cache_key(
            cache_kind,
            identity,
            schema_version=schema_version,
        )
        request = {
            "cache_key": cache_key,
            "cache_kind": str(cache_kind or ""),
            "repository": str(repository or ""),
            "identity": identity,
            "cache_status": cache_status,
            "schema_version": int(schema_version),
            "expires_at": expires_at.isoformat(),
        }
        payload_json = _dump(payload)
        now_text = now.isoformat()
        status = "completed" if cache_status == "complete" else "partial_success"
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO rag_runs(
                    id, kind, status, request, result, error, index_version,
                    version, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, '', ?, 1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    request = excluded.request,
                    result = excluded.result,
                    error = '',
                    index_version = excluded.index_version,
                    version = rag_runs.version + 1,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at
                """,
                (
                    _row_id(cache_key),
                    CACHE_RUN_KIND,
                    status,
                    _dump(request),
                    payload_json,
                    int(schema_version),
                    now_text,
                    now_text,
                    now_text,
                ),
            )
        return self.get(
            cache_kind,
            identity,
            schema_version=schema_version,
            allow_partial=True,
        )

    def delete_key(self, cache_key: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM rag_runs WHERE id = ? AND kind = ?",
                (_row_id(cache_key), CACHE_RUN_KIND),
            )
        return cursor.rowcount == 1

    def delete_expired(self) -> int:
        expired_ids: list[str] = []
        now = _utc_now()
        for row in self._rows(limit=5000):
            request = _load_object(row["request"])
            expires_at = _timestamp(str(request.get("expires_at") or ""))
            if expires_at is None or expires_at <= now:
                expired_ids.append(str(row["id"]))
        if not expired_ids:
            return 0
        with self.database.connect() as connection:
            connection.executemany(
                "DELETE FROM rag_runs WHERE id = ? AND kind = ?",
                [(row_id, CACHE_RUN_KIND) for row_id in expired_ids],
            )
        return len(expired_ids)

    def clear(
        self,
        *,
        repository: str = "",
        cache_kind: str = "",
    ) -> int:
        row_ids: list[str] = []
        for row in self._rows(limit=5000):
            request = _load_object(row["request"])
            if repository and str(request.get("repository") or "") != repository:
                continue
            if cache_kind and str(request.get("cache_kind") or "") != cache_kind:
                continue
            row_ids.append(str(row["id"]))
        if not row_ids:
            return 0
        with self.database.connect() as connection:
            connection.executemany(
                "DELETE FROM rag_runs WHERE id = ? AND kind = ?",
                [(row_id, CACHE_RUN_KIND) for row_id in row_ids],
            )
        return len(row_ids)

    def manifest(self) -> dict[str, Any]:
        now = _utc_now()
        entries = 0
        complete = 0
        partial = 0
        expired = 0
        total_bytes = 0
        by_kind: dict[str, dict[str, int]] = {}
        by_repository: dict[str, int] = {}
        for row in self._rows(limit=5000):
            request = _load_object(row["request"])
            status = str(request.get("cache_status") or "")
            kind = str(request.get("cache_kind") or "unknown")
            repository = str(request.get("repository") or "unknown")
            expires_at = _timestamp(str(request.get("expires_at") or ""))
            size_bytes = len(str(row["result"] or "").encode("utf-8"))
            entries += 1
            total_bytes += size_bytes
            complete += int(status == "complete")
            partial += int(status == "partial")
            expired += int(expires_at is None or expires_at <= now)
            kind_bucket = by_kind.setdefault(
                kind,
                {"entries": 0, "complete": 0, "partial": 0, "bytes": 0},
            )
            kind_bucket["entries"] += 1
            kind_bucket["complete"] += int(status == "complete")
            kind_bucket["partial"] += int(status == "partial")
            kind_bucket["bytes"] += size_bytes
            by_repository[repository] = by_repository.get(repository, 0) + 1
        return {
            "kind": CACHE_RUN_KIND,
            "entries": entries,
            "complete_entries": complete,
            "partial_entries": partial,
            "expired_entries": expired,
            "total_bytes": total_bytes,
            "by_kind": dict(sorted(by_kind.items())),
            "by_repository": dict(sorted(by_repository.items())),
        }

    def _rows(self, *, limit: int) -> list[Any]:
        safe_limit = max(1, min(int(limit), 5000))
        with self.database.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT * FROM rag_runs
                    WHERE kind = ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (CACHE_RUN_KIND, safe_limit),
                ).fetchall()
            )

    @staticmethod
    def _entry_from_row(row: Any) -> GitHubResearchCacheEntry | None:
        request = _load_object(row["request"])
        payload = _load_object(row["result"])
        cache_key = str(request.get("cache_key") or "")
        cache_kind = str(request.get("cache_kind") or "")
        if not cache_key or not cache_kind or payload.get("ok") is not True:
            return None
        return GitHubResearchCacheEntry(
            cache_key=cache_key,
            cache_kind=cache_kind,
            repository=str(request.get("repository") or ""),
            identity=dict(request.get("identity") or {}),
            payload=payload,
            cache_status=str(request.get("cache_status") or ""),
            schema_version=int(request.get("schema_version") or 0),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
            expires_at=str(request.get("expires_at") or ""),
            size_bytes=len(str(row["result"] or "").encode("utf-8")),
        )
