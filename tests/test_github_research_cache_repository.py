from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_research_cache_repository import (
    CACHE_RUN_KIND,
    GitHubResearchCacheRepository,
    stable_cache_key,
)


def _repository(tmp_path) -> tuple[RuntimeDatabase, GitHubResearchCacheRepository]:
    database = RuntimeDatabase(tmp_path / "runtime.db")
    return database, GitHubResearchCacheRepository(database)


def test_complete_cache_survives_repository_restart(tmp_path):
    database, first = _repository(tmp_path)
    identity = {"repository": "openai/example", "number": 7}
    payload = {"ok": True, "status": "resolved", "provider_status": "complete"}

    stored = first.put(
        "pull_request",
        "openai/example",
        identity,
        payload,
        ttl_seconds=300,
        schema_version=2,
    )
    second = GitHubResearchCacheRepository(database)
    restored = second.get(
        "pull_request",
        identity,
        schema_version=2,
    )

    assert stored is not None
    assert restored is not None
    assert restored.payload == payload
    assert restored.cache_status == "complete"
    assert restored.cache_key == stable_cache_key(
        "pull_request",
        identity,
        schema_version=2,
    )


def test_partial_cache_is_short_lived_evidence_not_default_reuse(tmp_path):
    _database, repository = _repository(tmp_path)
    identity = {"repository": "openai/example", "number": 7}
    payload = {"ok": True, "status": "resolved", "provider_status": "partial"}

    repository.put(
        "pull_request",
        "openai/example",
        identity,
        payload,
        ttl_seconds=30,
    )

    assert repository.get("pull_request", identity) is None
    partial = repository.get("pull_request", identity, allow_partial=True)
    assert partial is not None
    assert partial.cache_status == "partial"


def test_failed_result_is_never_persisted(tmp_path):
    _database, repository = _repository(tmp_path)
    identity = {"repository": "openai/example", "number": 404}

    stored = repository.put(
        "pull_request",
        "openai/example",
        identity,
        {"ok": False, "status": "not_found", "error": "missing"},
        ttl_seconds=300,
    )

    assert stored is None
    assert repository.manifest()["entries"] == 0


def test_schema_version_mismatch_invalidates_entry(tmp_path):
    _database, repository = _repository(tmp_path)
    identity = {"repository": "openai/example", "base": "a", "head": "b"}
    repository.put(
        "change_impact",
        "openai/example",
        identity,
        {"ok": True, "status": "resolved", "provider_status": "complete"},
        ttl_seconds=300,
        schema_version=1,
    )

    assert repository.get(
        "change_impact",
        identity,
        schema_version=2,
    ) is None


def test_expired_cleanup_manifest_and_scoped_clear(tmp_path):
    database, repository = _repository(tmp_path)
    repository.put(
        "pull_request",
        "openai/example",
        {"repository": "openai/example", "number": 1},
        {"ok": True, "status": "resolved", "provider_status": "complete"},
        ttl_seconds=300,
    )
    repository.put(
        "issue",
        "openai/example",
        {"repository": "openai/example", "number": 2},
        {"ok": True, "status": "resolved", "provider_status": "partial"},
        ttl_seconds=30,
    )
    repository.put(
        "checks",
        "other/repo",
        {"repository": "other/repo", "commit_sha": "a" * 40},
        {"ok": True, "status": "resolved", "provider_status": "complete"},
        ttl_seconds=300,
    )

    with database.connect() as connection:
        row = connection.execute(
            "SELECT id, request FROM rag_runs WHERE kind = ? ORDER BY id LIMIT 1",
            (CACHE_RUN_KIND,),
        ).fetchone()
        request = json.loads(row["request"])
        request["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        connection.execute(
            "UPDATE rag_runs SET request = ? WHERE id = ?",
            (json.dumps(request, ensure_ascii=False, sort_keys=True), row["id"]),
        )

    before = repository.manifest()
    assert before["entries"] == 3
    assert before["complete_entries"] == 2
    assert before["partial_entries"] == 1
    assert before["expired_entries"] == 1
    assert before["total_bytes"] > 0

    assert repository.delete_expired() == 1
    assert repository.clear(repository="openai/example", cache_kind="issue") in {0, 1}
    after = repository.manifest()
    assert after["expired_entries"] == 0
    assert after["entries"] == 1
    assert after["by_repository"] == {"other/repo": 1}
