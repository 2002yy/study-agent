from __future__ import annotations

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_gateway import ResearchWebGateway
from src.web.tool_gateway import GeneralWebGateway


class FakeGitHubReader:
    def supports(self, url: str) -> bool:
        return "github.com" in url

    def read(self, url: str, *, max_chars: int):
        return {
            "ok": True,
            "kind": "repository",
            "repository": "openai/example",
            "url": url,
            "default_branch": "main",
            "readme": "# Example repository",
            "entries": [{"path": "src/app.py", "type": "file"}],
        }

    def search_repository(self, repo_url: str, query: str, *, max_results: int):
        raise AssertionError("direct repository reading should not call code search")


def test_pasted_github_url_skips_search_provider_and_is_read_directly(tmp_path):
    general = GeneralWebGateway(github_reader=FakeGitHubReader())  # type: ignore[arg-type]
    gateway = ResearchWebGateway(general)
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(repository, gateway)
    url = "https://github.com/openai/example"

    run = service.lookup(url, max_items=5)

    assert len(run.query_attempts) == 1
    assert run.query_attempts[0]["query"] == url
    assert run.query_attempts[0]["status"] == "found"
    assert run.items[0]["source_type"] == "github_source"
    assert run.selected_sources[0]["read"]["kind"] == "repository"
    assert run.selected_sources[0]["read"]["entries"][0]["path"] == "src/app.py"
    assert run.stop_reason == "sources_read"
    assert "Example repository" in run.source_block
