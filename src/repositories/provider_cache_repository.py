"""Versioned, TTL-bound cache for immutable provider evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.infrastructure.sqlite.database import RuntimeDatabase


PROVIDER_CACHE_SCHEMA_VERSION = 1
REUSABLE_CLASSES = frozenset({"complete", "partial"})


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def provider_cache_key(
    *,
    kind: str,
    repository: str,
    request: dict[str, Any],
    immutable_refs: dict[str, Any] | None = None,
) -> str:
    """Return a stable key whose identity includes the cache schema version."""

    identity = {
        "schema_version": PROVIDER_CACHE_SCHEMA_VERSION,
        "kind": str(kind).strip().lower(),
        "repository": str(repository).strip().lower(),
        "request": request,
        "immutable_refs": immutable_refs or {},
    }
    digest = hashlib.sha256(_dump(identity).encode("utf-8")).hexdigest()
    return f"provider-cache:v{PROVIDER_CACHE_SCHEMA_VERSION}:{digest}"


def reusable_ttl_seconds(reuse_class: str, requested_ttl_seconds: int) -> int:
    """Bound weaker evidence so partial/failed responses cannot pollute the cache."""

    requested = max(0, int(requested_ttl_seconds))
    if reuse_class == "complete":
        return requested
    if reuse_class == "partial":
        return min(requested, 60)
    return 0


@dataclass(frozen=True)
class ProviderCacheEntry:
    cache_key: str
    schema_version: int
    kind: str
    repository: str
    payload: dict[str, Any]
    immutable_refs: dict[str, Any]
    provider_status: str
    budget: dict[str, Any]
    reuse_class: str
    created_at: str
    expires_at: str


class ProviderCacheRepository:
    def __init__(self, database: RuntimeDatabase) -> None:
        self.database = database
        self.database.initialize()

    def get(
        self,
        cache_key: str,
        *,
        now: datetime | None = None,
    ) -> ProviderCacheEntry | None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM provider_cache_entries
                WHERE cache_key = ? AND schema_version = ? AND expires_at > ?
                """,
                (cache_key, PROVIDER_CACHE_SCHEMA_VERSION, current.isoformat()),
            ).fetchone()
        if row is None or str(row["reuse_class"]) not in REUSABLE_CLASSES:
            return None
        return _entry_from_row(row)

    def put(
        self,
        *,
        cache_key: str,
        kind: str,
        repository: str,
        payload: dict[str, Any],
        immutable_refs: dict[str, Any],
        provider_status: str,
        budget: dict[str, Any],
        reuse_class: str,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> ProviderCacheEntry | None:
        ttl = reusable_ttl_seconds(reuse_class, ttl_seconds)
        if ttl <= 0:
            return None
        created = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expires = created + timedelta(seconds=ttl)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO provider_cache_entries(
                    cache_key, schema_version, kind, repository, payload,
                    immutable_refs, provider_status, budget, reuse_class,
                    created_at, expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    kind = excluded.kind,
                    repository = excluded.repository,
                    payload = excluded.payload,
                    immutable_refs = excluded.immutable_refs,
                    provider_status = excluded.provider_status,
                    budget = excluded.budget,
                    reuse_class = excluded.reuse_class,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (
                    cache_key,
                    PROVIDER_CACHE_SCHEMA_VERSION,
                    kind,
                    repository,
                    _dump(payload),
                    _dump(immutable_refs),
                    provider_status,
                    _dump(budget),
                    reuse_class,
                    created.isoformat(),
                    expires.isoformat(),
                    created.isoformat(),
                ),
            )
            connection.commit()
        return self.get(cache_key, now=created)

    def prune(
        self,
        *,
        repository: str | None = None,
        kind: str | None = None,
        now: datetime | None = None,
    ) -> int:
        clauses = ["expires_at <= ?"]
        values: list[Any] = [
            (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        ]
        if repository:
            clauses.append("repository = ?")
            values.append(repository)
        if kind:
            clauses.append("kind = ?")
            values.append(kind)
        with self.database.connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM provider_cache_entries WHERE {' AND '.join(clauses)}",
                values,
            )
        return cursor.rowcount

    def manifest(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT kind, repository, reuse_class, COUNT(*) AS entry_count,
                       SUM(LENGTH(payload)) AS payload_bytes,
                       MIN(created_at) AS oldest_created_at,
                       MAX(expires_at) AS latest_expires_at
                FROM provider_cache_entries
                GROUP BY kind, repository, reuse_class
                ORDER BY repository, kind, reuse_class
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        manifest = self.manifest()
        return {
            "entry_count": sum(int(item["entry_count"] or 0) for item in manifest),
            "payload_bytes": sum(int(item["payload_bytes"] or 0) for item in manifest),
        }


def _entry_from_row(row: Any) -> ProviderCacheEntry:
    return ProviderCacheEntry(
        cache_key=str(row["cache_key"]),
        schema_version=int(row["schema_version"]),
        kind=str(row["kind"]),
        repository=str(row["repository"]),
        payload=json.loads(row["payload"]),
        immutable_refs=json.loads(row["immutable_refs"]),
        provider_status=str(row["provider_status"]),
        budget=json.loads(row["budget"]),
        reuse_class=str(row["reuse_class"]),
        created_at=str(row["created_at"]),
        expires_at=str(row["expires_at"]),
    )
