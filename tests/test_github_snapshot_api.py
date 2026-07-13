from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_github_snapshot_service


class FakeGitHubSnapshotService:
    def snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
        force_refresh: bool = False,
    ) -> dict:
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref or "main",
            "tree_sha": "tree-123",
            "query": query,
            "snapshot_run_id": "rag_snapshot_1",
            "cache_hit": not force_refresh,
            "files": [{"path": "src/app.py", "sha": "sha-app"}],
        }

    def get(self, run_id: str) -> dict:
        if run_id != "rag_snapshot_1":
            raise ValueError(f"GitHub snapshot not found: {run_id}")
        return {
            "id": run_id,
            "status": "completed",
            "request": {"repository": "openai/example"},
            "result": {"ok": True, "tree_sha": "tree-123"},
            "error": "",
            "version": 2,
            "created_at": "2026-07-13T00:00:00+00:00",
            "updated_at": "2026-07-13T00:00:01+00:00",
            "completed_at": "2026-07-13T00:00:01+00:00",
        }

    def list(self, *, limit: int = 20) -> list[dict]:
        return [self.get("rag_snapshot_1")][:limit]


def test_github_snapshot_api_create_list_and_get():
    service = FakeGitHubSnapshotService()
    app.dependency_overrides[get_github_snapshot_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/github-repo-snapshots",
        json={
            "repo_url": "https://github.com/openai/example",
            "query": "architecture",
            "ref": "main",
        },
    )
    listed = client.get("/github-repo-snapshots")
    restored = client.get("/github-repo-snapshots/rag_snapshot_1")

    assert created.status_code == 200
    assert created.json()["result"]["tree_sha"] == "tree-123"
    assert listed.status_code == 200
    assert listed.json()["runs"][0]["id"] == "rag_snapshot_1"
    assert restored.status_code == 200
    assert restored.json()["result"]["tree_sha"] == "tree-123"
