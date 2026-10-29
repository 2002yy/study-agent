"""The merge trace has to reach the persisted run, not just the gateway.

#306 made ``GeneralWebGateway`` report how a search was really executed. The
research chain goes through ``ResearchWebGateway``, which returned only the
result list, so the evidence died one layer above the gateway. These tests pin
the whole path: gateway -> research adapter -> persisted ``query_attempts``.
"""

from __future__ import annotations

import pytest

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web import tool_gateway
from src.web.research_gateway import ResearchWebGateway
from src.web.tool_gateway import GeneralWebGateway


def _row(title: str, url: str, snippet: str = "") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet}


@pytest.fixture(autouse=True)
def _no_searxng(monkeypatch):
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: False)


def _patch_providers(monkeypatch, bing, ddg):
    monkeypatch.setattr(
        GeneralWebGateway, "_search_bing_rss", staticmethod(lambda *a, **k: bing())
    )
    monkeypatch.setattr(
        GeneralWebGateway, "_search_duckduckgo", staticmethod(lambda *a, **k: ddg())
    )


def _merge_gateway() -> ResearchWebGateway:
    return ResearchWebGateway(GeneralWebGateway(search_strategy="merge"))


def test_a_merge_search_exposes_the_execution_it_performed(monkeypatch):
    _patch_providers(
        monkeypatch,
        lambda: ([_row("python asyncio timeout", "https://a.example/1")], ""),
        lambda: ([_row("asyncio notes", "https://b.example/2")], ""),
    )
    gateway = _merge_gateway()

    results = gateway.search("python asyncio timeout", max_items=5)
    trace = gateway.search_trace()

    assert [item["url"] for item in results] == ["https://a.example/1", "https://b.example/2"]
    assert trace["search_strategy"] == "merge"
    assert trace["providers_attempted"] == ["bing_rss", "duckduckgo_html"]
    assert trace["provider_counts"] == {"bing_rss": 1, "duckduckgo_html": 1}
    assert trace["ranked_urls"] == [item["url"] for item in results]


def test_the_default_strategy_claims_no_merge(monkeypatch):
    """A run on the current arm must not look like the candidate arm."""

    _patch_providers(
        monkeypatch,
        lambda: ([_row("python asyncio timeout", "https://a.example/1")], ""),
        lambda: ([_row("other", "https://b.example/2")], ""),
    )
    gateway = ResearchWebGateway(GeneralWebGateway())

    gateway.search("python asyncio timeout", max_items=5)

    assert gateway.search_trace() == {}


def test_a_direct_github_url_is_not_a_search(monkeypatch):
    called: list[str] = []

    def bing():
        called.append("bing")
        return [], ""

    _patch_providers(monkeypatch, bing, lambda: ([], ""))
    gateway = _merge_gateway()

    gateway.search("https://github.com/2002yy/study-agent", max_items=5)

    assert called == []
    assert gateway.search_trace() == {}


def test_a_previous_trace_is_never_attached_to_a_later_search(monkeypatch):
    """Stale evidence is worse than none: it would describe another query."""

    _patch_providers(
        monkeypatch,
        lambda: ([_row("python asyncio timeout", "https://a.example/1")], ""),
        lambda: ([_row("asyncio notes", "https://b.example/2")], ""),
    )
    merge = _merge_gateway()
    merge.search("python asyncio timeout", max_items=5)
    assert merge.search_trace()["search_strategy"] == "merge"

    # Same gateway object, now on the fallback strategy.
    merge.gateway.search_strategy = "fallback"
    merge.search("python asyncio timeout", max_items=5)

    assert merge.search_trace() == {}


def test_a_failed_search_still_reports_which_providers_ran(monkeypatch):
    _patch_providers(
        monkeypatch,
        lambda: ([], "bing_rss:TimeoutError:timed out"),
        lambda: ([], "duckduckgo_html:HTTPError:503"),
    )
    gateway = _merge_gateway()

    with pytest.raises(RuntimeError, match="providers_failed"):
        gateway.search("python asyncio timeout", max_items=5)

    trace = gateway.search_trace()
    assert trace["providers_attempted"] == ["bing_rss", "duckduckgo_html"]
    assert trace["ranked_urls"] == []


def test_the_persisted_attempt_carries_the_search_trace(monkeypatch, tmp_path):
    """The run record is what Quality-0 can read after the process exits."""

    _patch_providers(
        monkeypatch,
        lambda: ([_row("python asyncio timeout", "https://a.example/1")], ""),
        lambda: ([_row("asyncio notes", "https://b.example/2")], ""),
    )
    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = WebLookupService(WebLookupRepository(database), _merge_gateway())

    created = service.lookup("python asyncio timeout", max_items=5)
    restored = WebLookupRepository(database).get(created.id)

    assert restored is not None
    attempt = restored.query_attempts[0]
    assert attempt["query"] == "python asyncio timeout"
    assert attempt["search_trace"]["search_strategy"] == "merge"
    assert attempt["search_trace"]["providers_attempted"] == [
        "bing_rss",
        "duckduckgo_html",
    ]


def test_the_default_arm_records_no_trace_field(monkeypatch, tmp_path):
    _patch_providers(
        monkeypatch,
        lambda: ([_row("python asyncio timeout", "https://a.example/1")], ""),
        lambda: ([_row("other", "https://b.example/2")], ""),
    )
    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = WebLookupService(
        WebLookupRepository(database), ResearchWebGateway(GeneralWebGateway())
    )

    created = service.lookup("python asyncio timeout", max_items=5)
    restored = WebLookupRepository(database).get(created.id)

    assert restored is not None
    assert "search_trace" not in restored.query_attempts[0]


def test_a_gateway_without_a_trace_reader_still_works(tmp_path):
    """Older adapters and test doubles must not break; they just report nothing."""

    class PlainGateway:
        def search(self, query: str, *, max_items: int):
            return [{"title": "Result", "url": "https://example.com/1", "search_excerpt": query}]

        def warnings(self):
            return []

    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = WebLookupService(WebLookupRepository(database), PlainGateway())

    created = service.lookup("plain lookup", max_items=3)
    restored = WebLookupRepository(database).get(created.id)

    assert restored is not None
    assert "search_trace" not in restored.query_attempts[0]
