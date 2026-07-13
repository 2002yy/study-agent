from __future__ import annotations

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class ReadableGateway:
    def __init__(self, items: list[dict], reads: dict[str, object]):
        self.items = items
        self.reads = reads
        self.search_calls: list[str] = []
        self.read_calls: list[tuple[str, int]] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict]:
        self.search_calls.append(query)
        return [dict(item) for item in self.items[:max_items]]

    def read(self, url: str, *, max_chars: int = 6000) -> dict:
        self.read_calls.append((url, max_chars))
        result = self.reads[url]
        if isinstance(result, Exception):
            raise result
        return dict(result)

    def warnings(self) -> list[dict]:
        return []


def _service(tmp_path, gateway: ReadableGateway) -> WebLookupService:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    return WebLookupService(repository, gateway)


def test_lookup_reads_selected_page_and_persists_excerpt(tmp_path):
    url = "https://example.com/alpha"
    gateway = ReadableGateway(
        [
            {
                "title": "Alpha official documentation",
                "url": url,
                "link": url,
                "source": "example.com",
                "snippet": "Alpha reference",
            }
        ],
        {
            url: {
                "ok": True,
                "kind": "web_page",
                "url": url,
                "method": "local_html",
                "content": "Alpha is documented here. " * 20,
            }
        },
    )
    service = _service(tmp_path, gateway)

    run = service.lookup("Alpha", max_items=5)
    restored = service.get(run.id)

    assert run.stage == "completed"
    assert run.stop_reason == "sources_read"
    assert run.provider_status == "found"
    assert run.research_context["read_summary"] == {
        "attempted": 1,
        "successful": 1,
        "failed": 0,
        "skipped": 0,
        "used_chars": len("Alpha is documented here. " * 20),
        "budget": {
            "max_reads": 3,
            "max_chars_per_source": 6000,
            "max_total_chars": 16000,
        },
    }
    assert run.selected_sources[0]["read"]["status"] == "read"
    assert "Alpha is documented here" in run.source_block
    assert restored == run


def test_lookup_keeps_successful_reads_when_another_source_fails(tmp_path):
    first = "https://example.com/alpha-one"
    second = "https://example.org/alpha-two"
    gateway = ReadableGateway(
        [
            {
                "title": "Alpha primary source",
                "url": first,
                "link": first,
                "source": "example.com",
            },
            {
                "title": "Alpha secondary source",
                "url": second,
                "link": second,
                "source": "example.org",
            },
        ],
        {
            first: {"ok": True, "kind": "web_page", "content": "primary text"},
            second: {"ok": False, "error": "timeout", "url": second},
        },
    )
    service = _service(tmp_path, gateway)

    run = service.lookup("Alpha", max_items=5)

    assert run.status == "completed"
    assert run.provider_status == "partial"
    assert run.stop_reason == "sources_partially_read"
    assert run.research_context["read_summary"]["successful"] == 1
    assert run.research_context["read_summary"]["failed"] == 1
    assert run.selected_sources[0]["read"]["status"] == "read"
    assert run.selected_sources[1]["read"]["status"] == "failed"
    assert any("source read failed" in warning for warning in run.warnings)


def test_lookup_enforces_read_count_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_RESEARCH_MAX_READS", "1")
    first = "https://example.com/alpha-one"
    second = "https://example.org/alpha-two"
    gateway = ReadableGateway(
        [
            {
                "title": "Alpha first source",
                "url": first,
                "link": first,
                "source": "example.com",
            },
            {
                "title": "Alpha second source",
                "url": second,
                "link": second,
                "source": "example.org",
            },
        ],
        {
            first: {"ok": True, "kind": "web_page", "content": "first"},
            second: {"ok": True, "kind": "web_page", "content": "second"},
        },
    )
    service = _service(tmp_path, gateway)

    run = service.lookup("Alpha", max_items=5)

    assert gateway.read_calls == [(first, 6000)]
    assert run.research_context["read_summary"]["attempted"] == 1
    assert run.research_context["read_summary"]["successful"] == 1
    assert run.research_context["read_summary"]["skipped"] == 1
    assert run.selected_sources[1]["read"]["reason"] == "read_budget_exhausted"


def test_lookup_persists_github_repository_structure(tmp_path):
    repo_url = "https://github.com/openai/example"
    gateway = ReadableGateway(
        [
            {
                "title": "openai/example GitHub repository",
                "url": repo_url,
                "link": repo_url,
                "source": "github.com",
                "snippet": "Example source repository",
            }
        ],
        {
            repo_url: {
                "ok": True,
                "kind": "repository",
                "repository": "openai/example",
                "default_branch": "main",
                "readme": "# Example\nSource repository",
                "entries": [
                    {"path": "src/app.py", "type": "file"},
                    {"path": "tests/test_app.py", "type": "file"},
                ],
            }
        },
    )
    service = _service(tmp_path, gateway)

    run = service.lookup("openai example", max_items=5)

    read = run.selected_sources[0]["read"]
    assert read["kind"] == "repository"
    assert read["default_branch"] == "main"
    assert read["entries"][0]["path"] == "src/app.py"
    assert "Source repository" in run.source_block
