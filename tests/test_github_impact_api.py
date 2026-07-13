from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_github_snapshot_service


SNAPSHOT = {
    "ok": True,
    "repository": "openai/example",
    "ref": "main",
    "tree_sha": "tree-api-impact",
    "snapshot_run_id": "rag_impact_1",
    "cache_hit": True,
    "cache_mode": "exact",
    "files": [
        {
            "path": "src/repository.py",
            "sha": "sha-repository",
            "content": """class Repository:\n    def save(self, value):\n        return value\n""",
        },
        {
            "path": "src/service.py",
            "sha": "sha-service",
            "content": """from .repository import Repository\n\nclass Service:\n    def __init__(self, repository: Repository):\n        self.repository = repository\n\n    def execute(self, value):\n        return self.repository.save(value)\n""",
        },
        {
            "path": "tests/test_service.py",
            "sha": "sha-test",
            "content": """from src.service import Service\n\ndef test_execute():\n    assert Service(None).execute('x') == 'x'\n""",
        },
    ],
}


class FakeSnapshotService:
    def snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
        force_refresh: bool = False,
    ) -> dict:
        del repo_url, query, force_refresh
        return {**SNAPSHOT, "ref": ref or "main"}


def test_github_structure_includes_semantic_resolution_and_identity():
    service = FakeSnapshotService()
    app.dependency_overrides[get_github_snapshot_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/github-repo-structure",
            json={
                "repo_url": "https://github.com/openai/example",
                "symbol": "Repository.save",
                "ref": "main",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["resolution"]["status"] == "resolved"
    assert result["symbol_identities"][0]["id"].startswith("symbol_")
    assert "implementations" in result


def test_github_impact_api_returns_upstream_files_and_tests():
    service = FakeSnapshotService()
    app.dependency_overrides[get_github_snapshot_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/github-repo-impact",
            json={
                "repo_url": "https://github.com/openai/example",
                "symbol": "Repository.save",
                "ref": "main",
                "depth": 3,
                "max_files": 20,
                "max_edges": 50,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["resolution"]["status"] == "resolved"
    assert {item["path"] for item in result["files"]} >= {
        "src/repository.py",
        "src/service.py",
    }
    assert {item["path"] for item in result["tests"]} == {
        "tests/test_service.py"
    }
    assert result["stats"]["test_count"] == 1
