from __future__ import annotations

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.provider_cache_repository import ProviderCacheRepository
from src.web.github_change_impact import GitHubChangeImpactService


REPO = "https://github.com/openai/example"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


BASE_SNAPSHOT = {
    "ok": True,
    "repository": "openai/example",
    "ref": BASE_SHA,
    "requested_ref": BASE_SHA,
    "commit_sha": BASE_SHA,
    "tree_sha": "tree-base",
    "file_count": 3,
    "files": [
        {
            "path": "src/service.py",
            "sha": "sha-service-old",
            "content": """def process(value):
    return normalize(value)

def normalize(value):
    return value.strip()
""",
        },
        {
            "path": "src/api.py",
            "sha": "sha-api-old",
            "content": """from .service import process

def handle(value):
    return process(value)
""",
        },
        {
            "path": "tests/test_service.py",
            "sha": "sha-test-old",
            "content": """def test_process():
    process = lambda value: value.strip()
    assert process(' x ') == 'x'
""",
        },
    ],
}

HEAD_SNAPSHOT = {
    "ok": True,
    "repository": "openai/example",
    "ref": HEAD_SHA,
    "requested_ref": HEAD_SHA,
    "commit_sha": HEAD_SHA,
    "tree_sha": "tree-head",
    "file_count": 3,
    "files": [
        {
            "path": "src/service.py",
            "sha": "sha-service-new",
            "content": """def process(value):
    return normalize(value)

def normalize(value, strict=False):
    cleaned = value.strip()
    return cleaned if strict else cleaned

def validate(value):
    return bool(value)
""",
        },
        {
            "path": "src/api.py",
            "sha": "sha-api-new",
            "content": """from .service import process

def handle(value):
    return process(value)
""",
        },
        {
            "path": "tests/test_service.py",
            "sha": "sha-test-new",
            "content": """def test_process():
    process = lambda value: value.strip()
    assert process(' x ') == 'x'
""",
        },
    ],
}


class FakeHistory:
    def __init__(self) -> None:
        self.calls = 0

    def compare(self, _repo_url: str, base: str, head: str, **_kwargs) -> dict:
        self.calls += 1
        assert base == "main"
        assert head == "feature"
        return {
            "ok": True,
            "status": "ahead",
            "repository": "openai/example",
            "base": {"ok": True, "commit_sha": BASE_SHA, "tree_sha": "tree-base"},
            "head": {"ok": True, "commit_sha": HEAD_SHA, "tree_sha": "tree-head"},
            "ahead_by": 1,
            "behind_by": 0,
            "total_commits": 1,
            "truncated": False,
            "files": [
                {
                    "filename": "src/service.py",
                    "previous_filename": "",
                    "status": "modified",
                    "patch_truncated": False,
                    "hunks": [
                        {
                            "old_start": 4,
                            "old_end": 5,
                            "new_start": 4,
                            "new_end": 10,
                        }
                    ],
                }
            ],
        }


class FakeSnapshotService:
    def __init__(self, *, missing_head: bool = False) -> None:
        self.missing_head = missing_head
        self.calls: list[tuple[str, str]] = []
        self.repo_calls: list[tuple[str, str, str]] = []

    def snapshot(self, repo_url: str, *, query: str, ref: str) -> dict:
        self.calls.append((query, ref))
        self.repo_calls.append((repo_url, query, ref))
        if ref == BASE_SHA:
            return BASE_SNAPSHOT
        if self.missing_head:
            return {
                **HEAD_SNAPSHOT,
                "file_count": 2,
                "files": [
                    item for item in HEAD_SNAPSHOT["files"] if item["path"] != "src/service.py"
                ],
            }
        return HEAD_SNAPSHOT


def test_change_impact_maps_modified_and_added_symbols_to_tests():
    snapshots = FakeSnapshotService()
    result = GitHubChangeImpactService(
        FakeHistory(),  # type: ignore[arg-type]
        snapshots,
    ).analyze(REPO, "main", "feature", max_files=10, max_symbols=20, depth=3)

    assert result["ok"] is True
    assert result["provider_status"] == "complete"
    assert result["summary"]["modified"] == 1
    assert result["summary"]["added"] == 1
    by_name = {
        (item.get("new") or item.get("old"))[0]["qualified_name"]: item
        for item in result["changes"]
    }
    normalized = by_name["normalize"]
    added = by_name["validate"]
    assert normalized["type"] == "modified"
    assert normalized["signature_changed"] is True
    assert normalized["old"][0]["identity"]["commit_sha"] == BASE_SHA
    assert normalized["new"][0]["identity"]["commit_sha"] == HEAD_SHA
    assert added["type"] == "added"
    assert {item["path"] for item in result["tests"]} == {"tests/test_service.py"}
    assert "validate" in result["missing_test_symbols"]
    assert {item["path"] for item in result["affected_files"]} >= {
        "src/service.py",
        "src/api.py",
    }
    assert snapshots.calls == [("src/service.py", BASE_SHA), ("src/service.py", HEAD_SHA)]


def test_change_impact_reports_missing_changed_file_in_snapshot():
    result = GitHubChangeImpactService(
        FakeHistory(),  # type: ignore[arg-type]
        FakeSnapshotService(missing_head=True),
    ).analyze(REPO, "main", "feature")

    assert result["ok"] is True
    assert result["provider_status"] == "partial"
    assert result["snapshots"]["head"]["missing_changed_paths"] == ["src/service.py"]
    assert {item["kind"] for item in result["uncertainties"]} >= {"missing_head_file"}
    assert result["summary"]["removed"] == 1


def test_change_impact_snapshots_cross_fork_sides_from_own_repositories():
    snapshots = FakeSnapshotService()
    base_repo_url = "https://github.com/openai/example"
    head_repo_url = "https://github.com/contributor/example"
    comparison = {
        "ok": True,
        "status": "cross_repository",
        "repository": "openai/example",
        "base": {
            "commit_sha": BASE_SHA,
            "repository": "openai/example",
            "repository_url": base_repo_url,
        },
        "head": {
            "commit_sha": HEAD_SHA,
            "repository": "contributor/example",
            "repository_url": head_repo_url,
        },
        "files": FakeHistory().compare(REPO, "main", "feature")["files"],
        "truncated": False,
    }

    result = GitHubChangeImpactService(
        FakeHistory(),  # type: ignore[arg-type]
        snapshots,
    ).analyze(
        REPO,
        BASE_SHA,
        HEAD_SHA,
        comparison=comparison,
        base_repo_url=base_repo_url,
        head_repo_url=head_repo_url,
    )

    assert result["ok"] is True
    assert result["cross_repository"] is True
    assert result["base_repository"] == "openai/example"
    assert result["head_repository"] == "contributor/example"
    assert result["snapshots"]["base"]["repository"] == "openai/example"
    assert result["snapshots"]["head"]["repository"] == "contributor/example"
    assert snapshots.repo_calls == [
        (base_repo_url, "src/service.py", BASE_SHA),
        (head_repo_url, "src/service.py", HEAD_SHA),
    ]


def test_cross_fork_cache_identity_includes_both_repositories(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    snapshots = FakeSnapshotService()
    service = GitHubChangeImpactService(
        FakeHistory(),  # type: ignore[arg-type]
        snapshots,
        ProviderCacheRepository(database),
    )
    base_ref = {
        "commit_sha": BASE_SHA,
        "repository": "openai/example",
        "repository_url": REPO,
    }
    files = FakeHistory().compare(REPO, "main", "feature")["files"]

    results = []
    for owner in ("contributor", "other-contributor"):
        head_repo_url = f"https://github.com/{owner}/example"
        results.append(
            service.analyze(
                REPO,
                BASE_SHA,
                HEAD_SHA,
                comparison={
                    "ok": True,
                    "status": "cross_repository",
                    "repository": "openai/example",
                    "base": base_ref,
                    "head": {
                        "commit_sha": HEAD_SHA,
                        "repository": f"{owner}/example",
                        "repository_url": head_repo_url,
                    },
                    "files": files,
                    "truncated": False,
                },
                base_repo_url=REPO,
                head_repo_url=head_repo_url,
            )
        )

    assert [result["cache_hit"] for result in results] == [False, False]
    assert len(snapshots.repo_calls) == 4


def test_change_impact_reuses_commit_pinned_result_after_restart(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    cache = ProviderCacheRepository(database)
    history = FakeHistory()
    snapshots = FakeSnapshotService()
    first = GitHubChangeImpactService(history, snapshots, cache).analyze(
        REPO,
        "main",
        "feature",
        max_files=10,
        max_symbols=20,
        depth=3,
    )

    restarted = GitHubChangeImpactService(
        history,
        snapshots,
        ProviderCacheRepository(database),
    ).analyze(
        REPO,
        "main",
        "feature",
        max_files=10,
        max_symbols=20,
        depth=3,
    )

    assert first["cache_hit"] is False
    assert restarted["cache_hit"] is True
    assert restarted["cache_mode"] == "persistent"
    assert history.calls == 2
    assert snapshots.calls == [
        ("src/service.py", BASE_SHA),
        ("src/service.py", HEAD_SHA),
    ]
