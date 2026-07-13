from __future__ import annotations

import base64
from datetime import datetime, timezone

import src.web.github_reader as github_reader
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.tools.web_agent import WebToolAgent
from src.web.github_reader import GitHubSourceReader, parse_github_url
from src.web.research_gateway import ResearchWebGateway
from src.web.tool_gateway import GeneralWebGateway


def test_parse_github_repository_blob_tree_and_raw_urls():
    repository = parse_github_url("https://github.com/openai/example")
    blob = parse_github_url(
        "https://github.com/openai/example/blob/main/src/app.py"
    )
    tree = parse_github_url(
        "https://github.com/openai/example/tree/main/src"
    )
    raw = parse_github_url(
        "https://raw.githubusercontent.com/openai/example/main/src/app.py"
    )

    assert repository is not None
    assert repository.repository == "openai/example"
    assert repository.kind == "repository"
    assert blob is not None
    assert (blob.kind, blob.ref, blob.path) == ("file", "main", "src/app.py")
    assert tree is not None
    assert (tree.kind, tree.ref, tree.path) == ("directory", "main", "src")
    assert raw is not None
    assert (raw.kind, raw.ref, raw.path) == ("file", "main", "src/app.py")
    assert parse_github_url("http://127.0.0.1/source.py") is None


def test_github_reader_reads_repository_root_without_live_network(monkeypatch):
    def fake_request_json(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {
                "default_branch": "main",
                "description": "Example repo",
                "language": "Python",
                "license": {"spdx_id": "MIT"},
            }
        if "/contents?" in url:
            return [
                {
                    "name": "src",
                    "path": "src",
                    "type": "dir",
                    "size": 0,
                    "sha": "tree-sha",
                    "html_url": "https://github.com/openai/example/tree/main/src",
                    "download_url": None,
                }
            ]
        if "/readme?" in url:
            return {
                "encoding": "base64",
                "content": base64.b64encode(b"# Example\nRepository README").decode(),
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)

    result = GitHubSourceReader().read("https://github.com/openai/example")

    assert result["ok"] is True
    assert result["kind"] == "repository"
    assert result["repository"] == "openai/example"
    assert result["default_branch"] == "main"
    assert "Repository README" in result["readme"]
    assert result["entries"][0]["path"] == "src"


def test_github_reader_reads_source_file_via_contents_api(monkeypatch):
    encoded = base64.b64encode(b"def hello():\n    return 'world'\n").decode()

    monkeypatch.setattr(
        github_reader,
        "_request_json",
        lambda _url, **_kwargs: {
            "encoding": "base64",
            "content": encoded,
            "sha": "blob-sha",
            "download_url": None,
        },
    )

    result = GitHubSourceReader().read(
        "https://github.com/openai/example/blob/main/src/app.py"
    )

    assert result["ok"] is True
    assert result["kind"] == "file"
    assert result["path"] == "src/app.py"
    assert result["sha"] == "blob-sha"
    assert "def hello" in result["content"]


def test_github_search_falls_back_to_bounded_tree_path_search_without_token(
    monkeypatch,
):
    def fake_request_json(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {"default_branch": "main"}
        if "/git/trees/" in url:
            return {
                "truncated": False,
                "tree": [
                    {
                        "path": "src/research/github_reader.py",
                        "type": "blob",
                        "size": 1200,
                        "sha": "reader-sha",
                    },
                    {
                        "path": "assets/logo.png",
                        "type": "blob",
                        "size": 300,
                        "sha": "image-sha",
                    },
                ],
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_reader, "_request_json", fake_request_json)
    monkeypatch.setattr(github_reader, "_token", lambda: "")

    result = GitHubSourceReader().search_repository(
        "https://github.com/openai/example",
        "github reader",
        max_results=5,
    )

    assert result["ok"] is True
    assert result["mode"] == "tree_path_fallback"
    assert result["warning"] == "content_search_requires_github_token"
    assert [item["path"] for item in result["results"]] == [
        "src/research/github_reader.py"
    ]


def test_general_gateway_dispatches_github_reads_and_searches():
    class FakeGitHubReader:
        def supports(self, url: str) -> bool:
            return "github.com" in url

        def read(self, url: str, *, max_chars: int):
            return {"ok": True, "kind": "file", "url": url, "content": "source"}

        def search_repository(self, repo_url: str, query: str, *, max_results: int):
            return {
                "ok": True,
                "repository": "openai/example",
                "query": query,
                "results": [{"path": "src/app.py"}],
            }

    gateway = GeneralWebGateway(github_reader=FakeGitHubReader())  # type: ignore[arg-type]

    read = gateway.read(
        "https://github.com/openai/example/blob/main/src/app.py",
        max_chars=2000,
    )
    searched = gateway.github_search(
        "https://github.com/openai/example",
        "app",
        max_results=3,
    )

    assert read["kind"] == "file"
    assert read["content"] == "source"
    assert searched["results"][0]["path"] == "src/app.py"


def test_research_gateway_uses_one_exact_general_search_step():
    class FakeGeneralGateway:
        def search_exact(self, query: str, *, max_results: int):
            return {
                "status": "ok",
                "reason": "results_found",
                "results": [
                    {
                        "title": "General result",
                        "url": "https://example.com/result",
                        "snippet": "result",
                        "source": "example.com",
                    }
                ],
                "provider_errors": ["searx timeout"],
                "searched_at": datetime.now(timezone.utc).isoformat(),
            }

    gateway = ResearchWebGateway(FakeGeneralGateway())  # type: ignore[arg-type]

    results = gateway.search("focused query", max_items=7)

    assert results[0]["title"] == "General result"
    assert gateway.warnings()[0]["message"] == "searx timeout"


def test_durable_web_lookup_defaults_to_general_research_gateway(tmp_path):
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(repository)

    assert isinstance(service.gateway, ResearchWebGateway)


def test_web_tool_agent_exposes_github_search_execution():
    class FakeGateway:
        def github_search(self, repo_url: str, query: str, *, max_results: int):
            return {
                "ok": True,
                "repository": repo_url,
                "query": query,
                "max_results": max_results,
            }

    agent = WebToolAgent(gateway=FakeGateway())  # type: ignore[arg-type]

    result = agent._execute(
        "github_search",
        {
            "repo_url": "https://github.com/openai/example",
            "query": "parser",
            "max_results": 6,
        },
    )

    assert result["ok"] is True
    assert result["query"] == "parser"
    assert result["max_results"] == 6
