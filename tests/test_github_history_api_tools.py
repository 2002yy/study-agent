from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.models.github import (
    GitHubBlameQueryRequest,
    GitHubCommitQueryRequest,
    GitHubCompareQueryRequest,
    GitHubRefQueryRequest,
)
from src.api.routes.github_routes import (
    compare_github_refs,
    inspect_github_blame,
    inspect_github_commit,
    resolve_github_ref,
)
from src.tools.web_agent import WEB_TOOLS, WebToolAgent
from src.web.evidence_pinning import pin_evidence_refs
from src.web.persistent_tool_gateway import PersistentGeneralWebGateway


class FakeSnapshotService:
    def search_repository(self, *_args, **_kwargs):
        return {"ok": False, "error": "not_used", "results": []}


class FakeHistoryService:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.ambiguous = ambiguous
        self.calls: list[tuple[str, tuple, dict]] = []

    def resolve_ref(self, repo_url: str, ref: str = ""):
        self.calls.append(("ref", (repo_url, ref), {}))
        if self.ambiguous:
            return {
                "ok": False,
                "status": "ambiguous",
                "error": "branch_tag_or_commit_ref_is_ambiguous",
                "candidates": [{"type": "branch"}, {"type": "tag"}],
            }
        return {"ok": True, "status": "resolved", "commit_sha": "a" * 40, "requested_ref": ref or "main"}

    def commit(self, repo_url: str, ref: str = ""):
        self.calls.append(("commit", (repo_url, ref), {}))
        return {"ok": True, "status": "resolved", "commit_sha": "b" * 40}

    def compare(self, repo_url: str, base: str, head: str, **kwargs):
        self.calls.append(("compare", (repo_url, base, head), kwargs))
        return {"ok": True, "status": "ahead", "files": []}

    def blame(self, repo_url: str, path: str, **kwargs):
        self.calls.append(("blame", (repo_url, path), kwargs))
        return {"ok": True, "status": "resolved", "ranges": []}


def test_history_routes_return_structured_results():
    service = FakeHistoryService()

    ref = resolve_github_ref(
        GitHubRefQueryRequest(repo_url="https://github.com/openai/example", ref="main"),
        service,  # type: ignore[arg-type]
    )
    commit = inspect_github_commit(
        GitHubCommitQueryRequest(repo_url="https://github.com/openai/example", ref="main"),
        service,  # type: ignore[arg-type]
    )
    compare = compare_github_refs(
        GitHubCompareQueryRequest(
            repo_url="https://github.com/openai/example",
            base="v1",
            head="v2",
            max_files=4,
            max_patch_chars=5000,
        ),
        service,  # type: ignore[arg-type]
    )
    blame = inspect_github_blame(
        GitHubBlameQueryRequest(
            repo_url="https://github.com/openai/example",
            path="src/app.py",
            ref="main",
            start_line=3,
            end_line=9,
        ),
        service,  # type: ignore[arg-type]
    )

    assert ref.result["commit_sha"] == "a" * 40
    assert commit.result["commit_sha"] == "b" * 40
    assert compare.result["status"] == "ahead"
    assert blame.result["status"] == "resolved"
    assert service.calls[2][2] == {"max_files": 4, "max_patch_chars": 5000}
    assert service.calls[3][2] == {"ref": "main", "start_line": 3, "end_line": 9}


def test_ambiguous_ref_route_returns_conflict():
    with pytest.raises(HTTPException) as captured:
        resolve_github_ref(
            GitHubRefQueryRequest(repo_url="https://github.com/openai/example", ref="release"),
            FakeHistoryService(ambiguous=True),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 409
    assert captured.value.detail["status"] == "ambiguous"


def test_model_tool_schema_and_dispatch_include_history_tools():
    names = {item["function"]["name"] for item in WEB_TOOLS}
    assert {"github_ref", "github_commit", "github_compare", "github_blame"} <= names

    history = FakeHistoryService()
    gateway = PersistentGeneralWebGateway(
        FakeSnapshotService(),  # type: ignore[arg-type]
        history_service=history,  # type: ignore[arg-type]
    )
    agent = WebToolAgent(gateway=gateway)

    ref = agent._execute(
        "github_ref",
        {"repo_url": "https://github.com/openai/example", "ref": "main"},
    )
    commit = agent._execute(
        "github_commit",
        {"repo_url": "https://github.com/openai/example", "ref": "abc1234"},
    )
    compare = agent._execute(
        "github_compare",
        {
            "repo_url": "https://github.com/openai/example",
            "base": "main",
            "head": "feature",
            "max_files": 7,
            "max_patch_chars": 9000,
        },
    )
    blame = agent._execute(
        "github_blame",
        {
            "repo_url": "https://github.com/openai/example",
            "path": "src/app.py",
            "ref": "main",
            "start_line": 10,
            "end_line": 20,
        },
    )

    assert ref["status"] == "resolved"
    assert commit["status"] == "resolved"
    assert compare["status"] == "ahead"
    assert blame["status"] == "resolved"
    assert history.calls[-2][2] == {"max_files": 7, "max_patch_chars": 9000}
    assert history.calls[-1][2] == {"ref": "main", "start_line": 10, "end_line": 20}


def test_evidence_pinning_recurses_without_overwriting_legacy_ref():
    payload = {
        "definitions": [
            {
                "evidence": {
                    "repository": "openai/example",
                    "ref": "main",
                    "tree_sha": "tree",
                    "path": "src/app.py",
                    "file_sha": "file",
                    "start_line": 5,
                    "end_line": 8,
                    "kind": "definition",
                }
            }
        ]
    }

    pinned = pin_evidence_refs(
        payload,
        {"ref": "main", "requested_ref": "main", "commit_sha": "a" * 40},
    )
    evidence = pinned["definitions"][0]["evidence"]

    assert evidence["ref"] == "main"
    assert evidence["requested_ref"] == "main"
    assert evidence["commit_sha"] == "a" * 40
