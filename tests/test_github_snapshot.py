from __future__ import annotations

import base64

import src.web.github_snapshot as github_snapshot
from src.tools.web_agent import WebToolAgent
from src.web.github_snapshot import GitHubRepositorySnapshotter, GitHubSnapshotBudget
from src.web.tool_gateway import GeneralWebGateway


def test_snapshot_ranks_related_source_and_excludes_generated_content(monkeypatch):
    blobs = {
        "sha-reader": "class GitHubSourceReader:\n    pass\n",
        "sha-service": "def lookup():\n    return 'ok'\n",
        "sha-readme": "# Example repository\n",
    }

    def fake_request_json(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {
                "default_branch": "main",
                "description": "Example",
                "language": "Python",
            }
        if "/git/trees/" in url:
            return {
                "sha": "tree-sha",
                "truncated": False,
                "tree": [
                    {
                        "path": "src/web/github_reader.py",
                        "type": "blob",
                        "size": 1200,
                        "sha": "sha-reader",
                    },
                    {
                        "path": "src/application/service.py",
                        "type": "blob",
                        "size": 900,
                        "sha": "sha-service",
                    },
                    {
                        "path": "README.md",
                        "type": "blob",
                        "size": 200,
                        "sha": "sha-readme",
                    },
                    {
                        "path": "node_modules/pkg/index.js",
                        "type": "blob",
                        "size": 100,
                        "sha": "sha-vendor",
                    },
                    {
                        "path": "package-lock.json",
                        "type": "blob",
                        "size": 100,
                        "sha": "sha-lock",
                    },
                    {
                        "path": "assets/logo.png",
                        "type": "blob",
                        "size": 100,
                        "sha": "sha-image",
                    },
                ],
            }
        for sha, text in blobs.items():
            if url.endswith(f"/git/blobs/{sha}"):
                return {
                    "sha": sha,
                    "encoding": "base64",
                    "content": base64.b64encode(text.encode()).decode(),
                }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_snapshot, "_request_json", fake_request_json)

    result = GitHubRepositorySnapshotter().snapshot(
        "https://github.com/openai/example",
        query="github reader",
        budget=GitHubSnapshotBudget(
            max_files=2,
            max_file_chars=1000,
            max_total_chars=2000,
            max_tree_entries=100,
        ),
    )

    assert result["ok"] is True
    assert result["repository"] == "openai/example"
    assert result["tree_sha"] == "tree-sha"
    assert result["file_count"] == 2
    paths = [item["path"] for item in result["files"]]
    assert paths[0] == "src/web/github_reader.py"
    assert "node_modules/pkg/index.js" not in paths
    assert "package-lock.json" not in paths
    assert "assets/logo.png" not in paths
    assert "GitHubSourceReader" in result["files"][0]["content"]


def test_snapshot_enforces_total_character_budget(monkeypatch):
    def fake_request_json(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {"default_branch": "main"}
        if "/git/trees/" in url:
            return {
                "sha": "tree-sha",
                "truncated": False,
                "tree": [
                    {
                        "path": "src/a.py",
                        "type": "blob",
                        "size": 100,
                        "sha": "sha-a",
                    },
                    {
                        "path": "src/b.py",
                        "type": "blob",
                        "size": 100,
                        "sha": "sha-b",
                    },
                ],
            }
        if "/git/blobs/" in url:
            return {
                "encoding": "base64",
                "content": base64.b64encode(("x" * 120).encode()).decode(),
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_snapshot, "_request_json", fake_request_json)

    result = GitHubRepositorySnapshotter().snapshot(
        "https://github.com/openai/example",
        budget=GitHubSnapshotBudget(
            max_files=10,
            max_file_chars=100,
            max_total_chars=150,
            max_tree_entries=100,
        ),
    )

    assert result["used_chars"] == 150
    assert result["file_count"] == 2
    assert len(result["files"][0]["content"]) == 100
    assert len(result["files"][1]["content"]) == 50
    assert result["files"][1]["truncated"] is True


def test_general_gateway_and_agent_dispatch_github_snapshot():
    class FakeSnapshotter:
        def snapshot(self, repo_url: str, *, query: str, ref: str):
            return {
                "ok": True,
                "repository": repo_url,
                "query": query,
                "ref": ref,
                "files": [{"path": "src/app.py"}],
            }

    gateway = GeneralWebGateway(
        github_snapshotter=FakeSnapshotter(),  # type: ignore[arg-type]
    )
    direct = gateway.github_snapshot(
        "https://github.com/openai/example",
        query="routing",
        ref="main",
    )
    agent = WebToolAgent(gateway=gateway)
    via_tool = agent._execute(
        "github_snapshot",
        {
            "repo_url": "https://github.com/openai/example",
            "query": "routing",
            "ref": "main",
        },
    )

    assert direct["files"][0]["path"] == "src/app.py"
    assert via_tool["query"] == "routing"
    assert via_tool["ref"] == "main"
