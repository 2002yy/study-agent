from __future__ import annotations

from src.application.github_snapshot_service import GitHubSnapshotService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_snapshot_repository import GitHubSnapshotRepository
from src.repositories.rag_repository import RagRepository


class FakeSnapshotter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def snapshot(self, repo_url: str, *, query: str = "", ref: str = "") -> dict:
        self.calls.append((repo_url, query, ref))
        return {
            "ok": True,
            "kind": "github_snapshot",
            "repository": "openai/example",
            "ref": ref or "main",
            "tree_sha": "tree-123",
            "query": query,
            "files": [
                {
                    "path": "src/web/github_reader.py",
                    "sha": "sha-reader",
                    "content": "class GitHubSourceReader: pass",
                    "score": 50,
                },
                {
                    "path": "src/application/chat_service.py",
                    "sha": "sha-chat",
                    "content": "def prepare_chat(): return True",
                    "score": 20,
                },
                {
                    "path": "tests/test_github_reader.py",
                    "sha": "sha-test",
                    "content": "def test_reader(): pass",
                    "score": 10,
                },
            ],
            "file_count": 3,
            "used_chars": 94,
            "read_failures": [],
            "budget": {"max_files": 24},
        }


def _service(tmp_path, snapshotter: FakeSnapshotter):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = GitHubSnapshotRepository(RagRepository(database))
    return database, GitHubSnapshotService(repository, snapshotter)  # type: ignore[arg-type]


def test_exact_snapshot_is_reused_after_repository_restart(tmp_path):
    snapshotter = FakeSnapshotter()
    database, first = _service(tmp_path, snapshotter)

    created = first.snapshot(
        "https://github.com/openai/example",
        query="github reader",
        ref="main",
    )
    second = GitHubSnapshotService(
        GitHubSnapshotRepository(RagRepository(database)),
        snapshotter,  # type: ignore[arg-type]
    )
    restored = second.snapshot(
        "https://github.com/openai/example",
        query="github reader",
        ref="main",
    )

    assert created["cache_hit"] is False
    assert restored["cache_hit"] is True
    assert restored["cache_mode"] == "exact"
    assert restored["snapshot_run_id"] == created["snapshot_run_id"]
    assert len(snapshotter.calls) == 1


def test_followup_reuses_relevant_files_without_fetching_github_again(tmp_path):
    snapshotter = FakeSnapshotter()
    _, service = _service(tmp_path, snapshotter)
    original = service.snapshot(
        "https://github.com/openai/example",
        query="architecture",
        ref="main",
    )

    followup = service.snapshot(
        "https://github.com/openai/example",
        query="GitHubSourceReader",
        ref="main",
    )

    assert followup["cache_hit"] is True
    assert followup["cache_mode"] == "followup_subset"
    assert followup["reused_snapshot_id"] == original["snapshot_run_id"]
    assert [item["path"] for item in followup["files"]] == [
        "src/web/github_reader.py"
    ]
    assert len(snapshotter.calls) == 1


def test_unrelated_followup_fetches_a_fresh_snapshot(tmp_path):
    snapshotter = FakeSnapshotter()
    _, service = _service(tmp_path, snapshotter)
    service.snapshot(
        "https://github.com/openai/example",
        query="github reader",
        ref="main",
    )

    fresh = service.snapshot(
        "https://github.com/openai/example",
        query="database migration",
        ref="main",
    )

    assert fresh["cache_hit"] is False
    assert fresh["cache_mode"] == "fresh"
    assert len(snapshotter.calls) == 2


def test_force_refresh_bypasses_exact_cache(tmp_path):
    snapshotter = FakeSnapshotter()
    _, service = _service(tmp_path, snapshotter)
    service.snapshot(
        "https://github.com/openai/example",
        query="github reader",
        ref="main",
    )

    refreshed = service.snapshot(
        "https://github.com/openai/example",
        query="github reader",
        ref="main",
        force_refresh=True,
    )

    assert refreshed["cache_hit"] is False
    assert len(snapshotter.calls) == 2


def test_snapshot_runs_are_listable_and_recoverable(tmp_path):
    snapshotter = FakeSnapshotter()
    _, service = _service(tmp_path, snapshotter)
    created = service.snapshot(
        "https://github.com/openai/example",
        query="github reader",
        ref="main",
    )

    restored = service.get(created["snapshot_run_id"])
    listed = service.list()

    assert restored["status"] == "completed"
    assert restored["result"]["tree_sha"] == "tree-123"
    assert created["snapshot_run_id"] in [item["id"] for item in listed]
