from __future__ import annotations

from src.application.github_snapshot_service import GitHubSnapshotService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_snapshot_repository import GitHubSnapshotRepository
from src.repositories.rag_repository import RagRepository


class FakeSnapshotter:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self, repo_url: str, *, query: str = "", ref: str = "") -> dict:
        self.calls += 1
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref or "main",
            "tree_sha": "tree-123",
            "files": [
                {
                    "path": "src/application/chat_service.py",
                    "sha": "sha-chat",
                    "url": "https://github.com/openai/example/blob/main/src/application/chat_service.py",
                    "content": "def prepare_chat_turn(message):\n    return message\n",
                },
                {
                    "path": "src/web/github_reader.py",
                    "sha": "sha-reader",
                    "url": "https://github.com/openai/example/blob/main/src/web/github_reader.py",
                    "content": "class GitHubSourceReader:\n    pass\n",
                },
            ],
            "file_count": 2,
            "used_chars": 90,
        }


def _service(tmp_path, snapshotter: FakeSnapshotter):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    return database, GitHubSnapshotService(
        GitHubSnapshotRepository(RagRepository(database)),
        snapshotter,  # type: ignore[arg-type]
    )


def test_search_repository_returns_line_level_hybrid_results(tmp_path):
    snapshotter = FakeSnapshotter()
    _, service = _service(tmp_path, snapshotter)

    result = service.search_repository(
        "https://github.com/openai/example",
        "prepare chat turn",
        ref="main",
    )

    assert result["ok"] is True
    assert result["mode"] == "local_snapshot_hybrid"
    assert result["results"][0]["path"] == "src/application/chat_service.py"
    assert result["results"][0]["line_range"] == "L1-L2"
    assert result["results"][0]["score_breakdown"]["bm25"] > 0
    assert result["snapshot_run_id"]


def test_search_rebuilds_index_from_persisted_snapshot_after_restart(tmp_path):
    snapshotter = FakeSnapshotter()
    database, first = _service(tmp_path, snapshotter)
    first_result = first.search_repository(
        "https://github.com/openai/example",
        "GitHubSourceReader",
        ref="main",
    )

    second = GitHubSnapshotService(
        GitHubSnapshotRepository(RagRepository(database)),
        snapshotter,  # type: ignore[arg-type]
    )
    restored = second.search_repository(
        "https://github.com/openai/example",
        "GitHubSourceReader",
        ref="main",
    )

    assert restored["results"][0]["path"] == "src/web/github_reader.py"
    assert restored["cache_hit"] is True
    assert restored["snapshot_run_id"] == first_result["snapshot_run_id"]
    assert snapshotter.calls == 1
