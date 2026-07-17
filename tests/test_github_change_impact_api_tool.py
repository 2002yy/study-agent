from __future__ import annotations

from src.api.models.github import GitHubChangeImpactQueryRequest
from src.api.routes.github_routes import inspect_github_change_impact
from src.tools.web_agent import WEB_TOOLS, WebToolAgent
from src.web.github_change_impact import GitHubChangeImpactService
from src.web.persistent_tool_gateway import PersistentGeneralWebGateway


REPO = "https://github.com/openai/example"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class EmptyHistory:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def compare(self, _repo_url: str, base: str, head: str, **kwargs) -> dict:
        self.calls.append({"base": base, "head": head, **kwargs})
        return {
            "ok": True,
            "status": "identical",
            "repository": "openai/example",
            "base": {"ok": True, "commit_sha": BASE_SHA, "tree_sha": "tree-base"},
            "head": {"ok": True, "commit_sha": HEAD_SHA, "tree_sha": "tree-head"},
            "ahead_by": 0,
            "behind_by": 0,
            "total_commits": 0,
            "truncated": False,
            "files": [],
        }


class EmptySnapshotService:
    def snapshot(self, _repo_url: str, *, query: str, ref: str) -> dict:
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref,
            "requested_ref": ref,
            "commit_sha": ref,
            "tree_sha": "tree-" + ref[:8],
            "file_count": 0,
            "files": [],
        }

    def search_repository(self, *_args, **_kwargs) -> dict:
        return {"ok": False, "error": "not_used", "results": []}


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def github_change_impact(self, repo_url: str, base: str, head: str, **kwargs) -> dict:
        self.calls.append((repo_url, base, head, kwargs))
        return {"ok": True, "base": base, "head": head, "budget": kwargs}


def test_change_impact_route_preserves_requested_budgets():
    history = EmptyHistory()
    response = inspect_github_change_impact(
        GitHubChangeImpactQueryRequest(
            repo_url=REPO,
            base="main",
            head="feature",
            max_files=7,
            max_symbols=8,
            depth=3,
            max_impact_files=9,
            max_edges=10,
        ),
        GitHubChangeImpactService(
            history,  # type: ignore[arg-type]
            EmptySnapshotService(),  # type: ignore[arg-type]
        ),
    )

    assert response.result["ok"] is True
    assert response.result["budget"] == {
        "max_files": 7,
        "max_symbols": 8,
        "depth": 3,
        "max_impact_files": 9,
        "max_edges": 10,
        "max_patch_chars": 160_000,
    }
    assert history.calls[0]["max_files"] == 7


def test_persistent_gateway_bounds_change_impact_arguments():
    history = EmptyHistory()
    gateway = PersistentGeneralWebGateway(
        EmptySnapshotService(),  # type: ignore[arg-type]
        history_service=history,  # type: ignore[arg-type]
    )

    result = gateway.github_change_impact(
        REPO,
        "main",
        "feature",
        max_files=999,
        max_symbols=999,
        depth=99,
        max_impact_files=999,
        max_edges=999,
    )

    assert result["budget"] == {
        "max_files": 50,
        "max_symbols": 300,
        "depth": 4,
        "max_impact_files": 100,
        "max_edges": 500,
        "max_patch_chars": 160_000,
    }
    assert history.calls[0]["max_files"] == 50


def test_change_impact_model_tool_schema_and_dispatch():
    tool = next(
        item for item in WEB_TOOLS if item["function"]["name"] == "github_change_impact"
    )
    assert tool["function"]["parameters"]["required"] == ["repo_url", "base", "head"]

    gateway = FakeGateway()
    result = WebToolAgent(gateway=gateway)._execute(
        "github_change_impact",
        {
            "repo_url": REPO,
            "base": "main",
            "head": "feature",
            "max_files": 7,
            "max_symbols": 8,
            "depth": 3,
            "max_impact_files": 9,
            "max_edges": 10,
        },
    )

    assert result["budget"]["max_symbols"] == 8
    assert gateway.calls == [
        (
            REPO,
            "main",
            "feature",
            {
                "max_files": 7,
                "max_symbols": 8,
                "depth": 3,
                "max_impact_files": 9,
                "max_edges": 10,
            },
        )
    ]


def test_change_impact_model_tool_reports_unavailable_gateway():
    result = WebToolAgent(gateway=object())._execute(  # type: ignore[arg-type]
        "github_change_impact",
        {"repo_url": REPO, "base": "main", "head": "feature"},
    )

    assert result == {"ok": False, "error": "github_change_impact_unavailable"}
