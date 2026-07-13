from __future__ import annotations

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
            "content": """from src.service import process

def test_process():
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
            "content": """from src.service import process

def test_process():
    assert process(' x ') == 'x'
""",
        },
    ],
}


class FakeHistory:
    def compare(self, _repo_url: str, base: str, head: str, **_kwargs) -> dict:
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

    def snapshot(self, _repo_url: str, *, query: str, ref: str) -> dict:
        self.calls.append((query, ref))
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
