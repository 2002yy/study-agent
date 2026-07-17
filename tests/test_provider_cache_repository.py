from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.provider_cache_repository import (
    PROVIDER_CACHE_SCHEMA_VERSION,
    ProviderCacheRepository,
    provider_cache_key,
    reusable_ttl_seconds,
)
from src.web.github_work_items import GitHubWorkItemService


REPOSITORY = "openai/example"
COMMIT_SHA = "a" * 40


def _repository(tmp_path) -> ProviderCacheRepository:
    return ProviderCacheRepository(RuntimeDatabase(tmp_path / "runtime.db"))


def _put(
    repository: ProviderCacheRepository,
    cache_key: str,
    *,
    reuse_class: str = "complete",
    now: datetime | None = None,
):
    return repository.put(
        cache_key=cache_key,
        kind="checks",
        repository=REPOSITORY,
        payload={"ok": True, "commit_sha": COMMIT_SHA},
        immutable_refs={"commit_sha": COMMIT_SHA},
        provider_status=reuse_class,
        budget={"max_provider_requests": 12},
        reuse_class=reuse_class,
        ttl_seconds=300,
        now=now,
    )


def test_provider_cache_key_is_canonical_and_schema_versioned():
    first = provider_cache_key(
        kind="checks",
        repository="OpenAI/Example",
        request={"max_jobs": 20, "include_jobs": True},
        immutable_refs={"commit_sha": COMMIT_SHA},
    )
    second = provider_cache_key(
        kind="CHECKS",
        repository=REPOSITORY,
        request={"include_jobs": True, "max_jobs": 20},
        immutable_refs={"commit_sha": COMMIT_SHA},
    )

    assert first == second
    assert first.startswith(f"provider-cache:v{PROVIDER_CACHE_SCHEMA_VERSION}:")
    assert provider_cache_key(
        kind="checks",
        repository=REPOSITORY,
        request={"include_jobs": True, "max_jobs": 21},
        immutable_refs={"commit_sha": COMMIT_SHA},
    ) != first


def test_cache_survives_repository_restart_and_expires(tmp_path):
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    cache_key = provider_cache_key(
        kind="checks",
        repository=REPOSITORY,
        request={"ref": COMMIT_SHA},
        immutable_refs={"commit_sha": COMMIT_SHA},
    )
    first = _repository(tmp_path)
    _put(first, cache_key, now=now)

    restarted = _repository(tmp_path)
    restored = restarted.get(cache_key, now=now + timedelta(seconds=299))

    assert restored is not None
    assert restored.payload["commit_sha"] == COMMIT_SHA
    assert restored.immutable_refs == {"commit_sha": COMMIT_SHA}
    assert restarted.get(cache_key, now=now + timedelta(seconds=300)) is None


def test_partial_is_short_lived_and_failed_is_not_reused(tmp_path):
    repository = _repository(tmp_path)
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    partial_key = provider_cache_key(
        kind="checks",
        repository=REPOSITORY,
        request={"case": "partial"},
    )
    failed_key = provider_cache_key(
        kind="checks",
        repository=REPOSITORY,
        request={"case": "failed"},
    )

    _put(repository, partial_key, reuse_class="partial", now=now)
    failed = _put(repository, failed_key, reuse_class="failed", now=now)

    assert reusable_ttl_seconds("partial", 300) == 60
    assert repository.get(partial_key, now=now + timedelta(seconds=59)) is not None
    assert repository.get(partial_key, now=now + timedelta(seconds=60)) is None
    assert failed is None
    assert repository.get(failed_key, now=now) is None


def test_manifest_stats_prune_and_concurrent_upsert(tmp_path):
    repository = _repository(tmp_path)
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    cache_key = provider_cache_key(
        kind="checks",
        repository=REPOSITORY,
        request={"case": "concurrent"},
    )

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(lambda _: _put(repository, cache_key, now=now), range(8)))

    assert all(entry is not None for entry in entries)
    assert repository.stats()["entry_count"] == 1
    assert repository.stats()["payload_bytes"] > 0
    assert repository.manifest()[0]["repository"] == REPOSITORY
    assert repository.prune(
        repository=REPOSITORY,
        kind="checks",
        now=now + timedelta(seconds=300),
    ) == 1


def test_checks_cache_reuses_immutable_evidence_after_service_restart(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    raw_key = f"checks-v2:{REPOSITORY}:{COMMIT_SHA}:10:20:30:1:12:3"
    payload = {
        "ok": True,
        "status": "resolved",
        "provider_status": "complete",
        "repository": REPOSITORY,
        "commit_sha": COMMIT_SHA,
        "provider_request_budget": {"max_requests": 12},
    }
    first = GitHubWorkItemService(
        cache_repository=ProviderCacheRepository(database)
    )
    first._cache_put(raw_key, payload)

    restarted = GitHubWorkItemService(
        cache_repository=ProviderCacheRepository(database)
    )
    restored = restarted._cache_get(raw_key)

    assert restored is not None
    assert restored["cache_hit"] is True
    assert restored["cache_mode"] == "persistent"
    assert restored["cache_schema_version"] == PROVIDER_CACHE_SCHEMA_VERSION


def test_moving_work_item_key_remains_memory_only(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    raw_key = f"pr-v2:{REPOSITORY}:42:20:10000:20:20:1:12:3"
    first = GitHubWorkItemService(
        cache_repository=ProviderCacheRepository(database)
    )
    first._cache_put(
        raw_key,
        {
            "ok": True,
            "status": "resolved",
            "repository": REPOSITORY,
            "head_sha": COMMIT_SHA,
        },
    )

    restarted = GitHubWorkItemService(
        cache_repository=ProviderCacheRepository(database)
    )

    assert restarted._cache_get(raw_key) is None
