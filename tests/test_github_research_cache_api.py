from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import (
    get_github_change_impact_service,
    get_github_research_cache_repository,
)


class FakeCacheRepository:
    def __init__(self) -> None:
        self.clear_calls: list[tuple[str, str]] = []
        self.expired_calls = 0
        self.entries = 3

    def manifest(self) -> dict:
        return {
            "kind": "github_research_cache",
            "entries": self.entries,
            "complete_entries": 2,
            "partial_entries": 1,
            "expired_entries": 0,
            "total_bytes": 123,
            "by_kind": {},
            "by_repository": {},
        }

    def delete_expired(self) -> int:
        self.expired_calls += 1
        return 2

    def clear(self, *, repository: str = "", cache_kind: str = "") -> int:
        self.clear_calls.append((repository, cache_kind))
        self.entries = 1
        return 2


class FakeChangeImpactService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict]] = []

    def analyze(self, repo_url: str, base: str, head: str, **kwargs) -> dict:
        self.calls.append((repo_url, base, head, kwargs))
        return {
            "ok": True,
            "status": "resolved",
            "provider_status": "complete",
            "base": base,
            "head": head,
        }


def test_cache_manifest_and_scoped_clear_endpoints():
    cache = FakeCacheRepository()
    app.dependency_overrides[get_github_research_cache_repository] = lambda: cache
    client = TestClient(app)

    try:
        manifest = client.get("/github-research-cache")
        cleared = client.delete(
            "/github-research-cache",
            params={"repository": "openai/example", "cache_kind": "checks"},
        )
        expired = client.delete(
            "/github-research-cache",
            params={"expired_only": "true"},
        )
    finally:
        app.dependency_overrides.pop(get_github_research_cache_repository, None)

    assert manifest.status_code == 200
    assert manifest.json()["result"]["entries"] == 3
    assert cleared.status_code == 200
    assert cleared.json()["result"]["deleted"] == 2
    assert cache.clear_calls == [("openai/example", "checks")]
    assert expired.status_code == 200
    assert expired.json()["result"]["expired_only"] is True
    assert cache.expired_calls == 1


def test_change_impact_endpoint_uses_cached_service_dependency():
    service = FakeChangeImpactService()
    app.dependency_overrides[get_github_change_impact_service] = lambda: service
    client = TestClient(app)

    try:
        response = client.post(
            "/github-change-impact",
            json={
                "repo_url": "https://github.com/openai/example",
                "base": "main",
                "head": "feature",
                "max_files": 10,
                "max_symbols": 20,
                "depth": 3,
                "max_impact_files": 30,
                "max_edges": 40,
            },
        )
    finally:
        app.dependency_overrides.pop(get_github_change_impact_service, None)

    assert response.status_code == 200
    assert service.calls == [
        (
            "https://github.com/openai/example",
            "main",
            "feature",
            {
                "max_files": 10,
                "max_symbols": 20,
                "depth": 3,
                "max_impact_files": 30,
                "max_edges": 40,
            },
        )
    ]
