from __future__ import annotations

from src.application.github_snapshot_service import GitHubSnapshotService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_snapshot_repository import GitHubSnapshotRepository
from src.repositories.rag_repository import RagRepository


COMMIT_SHA = "a" * 40


class FakeSnapshotter:
    def snapshot(self, repo_url: str, *, query: str = "", ref: str = "") -> dict:
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref or "main",
            "requested_ref": ref or "main",
            "commit_sha": COMMIT_SHA,
            "tree_sha": "tree-123",
            "files": [
                {
                    "path": "src/service.py",
                    "sha": "sha-service",
                    "url": f"https://github.com/openai/example/blob/{COMMIT_SHA}/src/service.py",
                    "content": """class Service:\n    def unrelated(self):\n        return 1\n\n    def prepare_chat_turn(self, message):\n        return message\n""",
                }
            ],
            "file_count": 1,
            "used_chars": 120,
        }


class FakeChecksService:
    def __init__(self, *, payload: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.payload = payload or {
            "ok": True,
            "status": "resolved",
            "provider_status": "complete",
            "commit_sha": COMMIT_SHA,
            "check_runs": [
                {
                    "name": "unit-tests",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://example.test/unit-tests",
                }
            ],
        }

    def checks(self, repo_url: str, **kwargs) -> dict:
        self.calls.append({"repo_url": repo_url, **kwargs})
        return dict(self.payload)


def _service(tmp_path, checks: FakeChecksService | None = None) -> GitHubSnapshotService:
    database = RuntimeDatabase(tmp_path / "runtime.db")
    return GitHubSnapshotService(
        GitHubSnapshotRepository(RagRepository(database)),
        FakeSnapshotter(),  # type: ignore[arg-type]
        checks,  # type: ignore[arg-type]
    )


def test_search_maps_match_to_innermost_symbol_and_pins_commit(tmp_path):
    service = _service(tmp_path)

    result = service.search_repository(
        "https://github.com/openai/example",
        "prepare chat turn",
        ref="main",
    )

    first = result["results"][0]
    assert first["match_line_range"] == "L5-L5"
    assert first["primary_symbol"]["qualified_name"] == "Service.prepare_chat_turn"
    assert first["evidence_ref"]["symbol"] == "Service.prepare_chat_turn"
    assert first["evidence_ref"]["symbol_kind"] == "method"
    assert first["evidence_ref"]["start_line"] == 5
    assert first["evidence_ref"]["end_line"] == 5
    assert first["evidence_ref"]["commit_sha"] == COMMIT_SHA
    assert result["ci_association"]["association"] == "not_requested"


def test_search_ci_is_requested_against_exact_snapshot_sha(tmp_path):
    checks = FakeChecksService()
    service = _service(tmp_path, checks)

    result = service.search_repository(
        "https://github.com/openai/example",
        "prepare chat turn",
        ref="main",
        include_ci=True,
    )

    assert checks.calls == [
        {
            "repo_url": "https://github.com/openai/example",
            "ref": COMMIT_SHA,
            "max_runs": 20,
            "max_checks": 100,
            "max_jobs": 1,
            "include_jobs": False,
        }
    ]
    assert result["ci_association"]["association"] == "verified_exact_sha"
    assert result["ci_association"]["overall_status"] == "success"
    assert result["commit_sha"] == result["ci_association"]["commit_sha"]


def test_ci_failure_does_not_invalidate_source_evidence(tmp_path):
    checks = FakeChecksService(
        payload={
            "ok": False,
            "status": "unavailable",
            "commit_sha": COMMIT_SHA,
            "error": "github_http_403",
        }
    )
    service = _service(tmp_path, checks)

    result = service.search_repository(
        "https://github.com/openai/example",
        "prepare chat turn",
        include_ci=True,
    )

    assert result["ok"] is True
    assert result["results"][0]["evidence_ref"]["commit_sha"] == COMMIT_SHA
    assert result["ci_association"]["association"] == "unavailable"
    assert result["ci_association"]["error"] == "github_http_403"
