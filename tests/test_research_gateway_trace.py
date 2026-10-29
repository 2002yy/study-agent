"""The merge trace has to reach the persisted run, tied to the search it came from.

#306 made ``GeneralWebGateway`` report how a search was really executed. The
research chain goes through ``ResearchWebGateway``, which returned only the
result list, so the evidence died one layer above the gateway.

An earlier attempt fetched the trace from the gateway *after* the search
returned. With one gateway shared by concurrent runs, another run could search
in between and its evidence would be recorded against the first run's answer.
These tests therefore pin two things: the trace reaches ``query_attempts``, and
it is produced by the same call that produced the results.
"""

from __future__ import annotations

import threading

import pytest

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web import tool_gateway
from src.web.research_gateway import ResearchSearchUnavailable, ResearchWebGateway
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


def _patch_providers_by_query(monkeypatch, bing, ddg):
    """Same, but the fakes see the query so two searches can differ."""

    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_bing_rss",
        staticmethod(lambda query, limit, timeout: bing(query)),
    )
    monkeypatch.setattr(
        GeneralWebGateway,
        "_search_duckduckgo",
        staticmethod(lambda query, limit, timeout: ddg(query)),
    )


def _merge_gateway() -> ResearchWebGateway:
    return ResearchWebGateway(GeneralWebGateway(search_strategy="merge"))


def test_a_merge_search_returns_the_trace_of_the_same_call(monkeypatch):
    _patch_providers(
        monkeypatch,
        lambda: ([_row("python asyncio timeout", "https://a.example/1")], ""),
        lambda: ([_row("asyncio notes", "https://b.example/2")], ""),
    )
    gateway = _merge_gateway()

    results, trace = gateway.search_with_trace("python asyncio timeout", max_items=5)

    assert [item["url"] for item in results] == [
        "https://a.example/1",
        "https://b.example/2",
    ]
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

    _results, trace = gateway.search_with_trace("python asyncio timeout", max_items=5)

    assert trace == {}


def test_a_direct_github_url_is_not_a_search(monkeypatch):
    called: list[str] = []

    def bing():
        called.append("bing")
        return [], ""

    _patch_providers(monkeypatch, bing, lambda: ([], ""))
    gateway = _merge_gateway()

    results, trace = gateway.search_with_trace(
        "https://github.com/2002yy/study-agent", max_items=5
    )

    assert called == []
    assert trace == {}
    assert results[0]["source_type"] == "github_source"


def test_the_gateway_exposes_no_shared_trace_accessor():
    """Evidence must not be readable from the object after the call.

    An accessor is what made a concurrent search able to overwrite another
    run's evidence; its absence is part of the contract now.
    """

    assert not hasattr(ResearchWebGateway(), "search_trace")


def test_evidence_belongs_to_the_call_that_produced_it(monkeypatch):
    """Search A, then search B on the same gateway, then look at A's evidence.

    This is the exact sequence that used to hand B's ranked URLs to A.
    """

    _patch_providers_by_query(
        monkeypatch,
        lambda query: (
            [
                _row(
                    f"{query} bing",
                    {
                        "alpha": "https://alpha.example/1",
                        "beta": "https://beta.example/2",
                    }[query.split()[0]],
                )
            ],
            "",
        ),
        lambda query: ([], ""),
    )
    gateway = _merge_gateway()

    results_a, trace_a = gateway.search_with_trace("alpha timeout", max_items=5)
    results_b, trace_b = gateway.search_with_trace("beta timeout", max_items=5)

    assert trace_a["ranked_urls"] == [item["url"] for item in results_a]
    assert trace_b["ranked_urls"] == [item["url"] for item in results_b]
    assert trace_a["ranked_urls"] == ["https://alpha.example/1"]
    assert trace_b["ranked_urls"] == ["https://beta.example/2"]


def test_a_search_completed_while_another_is_paused_keeps_its_own_trace(monkeypatch):
    """A blocks inside its provider call until B has finished entirely."""

    beta_done = threading.Event()

    def bing(query, limit, timeout):
        if query == "alpha timeout":
            assert beta_done.wait(5.0), "beta never completed"
            return [_row("alpha timeout", "https://alpha.example/1")], ""
        return [_row("beta timeout", "https://beta.example/2")], ""

    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(bing))
    monkeypatch.setattr(
        GeneralWebGateway, "_search_duckduckgo", staticmethod(lambda *a, **k: ([], ""))
    )
    gateway = _merge_gateway()
    captured: dict[str, tuple] = {}

    def run_alpha() -> None:
        captured["alpha"] = gateway.search_with_trace("alpha timeout", max_items=5)

    thread = threading.Thread(target=run_alpha)
    thread.start()
    captured["beta"] = gateway.search_with_trace("beta timeout", max_items=5)
    beta_done.set()
    thread.join(10)

    assert not thread.is_alive()
    alpha_results, alpha_trace = captured["alpha"]
    beta_results, beta_trace = captured["beta"]
    assert alpha_trace["ranked_urls"] == [item["url"] for item in alpha_results]
    assert beta_trace["ranked_urls"] == [item["url"] for item in beta_results]
    assert alpha_trace["ranked_urls"] == ["https://alpha.example/1"]
    assert beta_trace["ranked_urls"] == ["https://beta.example/2"]


def test_a_failed_search_carries_the_trace_of_what_it_attempted(monkeypatch):
    _patch_providers(
        monkeypatch,
        lambda: ([], "bing_rss:TimeoutError:timed out"),
        lambda: ([], "duckduckgo_html:HTTPError:503"),
    )
    gateway = _merge_gateway()

    with pytest.raises(ResearchSearchUnavailable, match="providers_failed") as caught:
        gateway.search_with_trace("python asyncio timeout", max_items=5)

    assert caught.value.search_trace["providers_attempted"] == [
        "bing_rss",
        "duckduckgo_html",
    ]
    assert caught.value.search_trace["ranked_urls"] == []


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


def test_two_interleaved_runs_persist_their_own_evidence(monkeypatch, tmp_path):
    """A paused run and a completed run must not share a trace row.

    Deterministic order: alpha blocks inside its provider call until beta has
    been searched *and persisted*, then alpha finishes and persists.
    """

    beta_persisted = threading.Event()

    def bing(query, limit, timeout):
        if query == "alpha timeout":
            assert beta_persisted.wait(5.0), "beta never persisted"
            return [_row("alpha timeout", "https://alpha.example/1")], ""
        return [_row("beta timeout", "https://beta.example/2")], ""

    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(bing))
    monkeypatch.setattr(
        GeneralWebGateway, "_search_duckduckgo", staticmethod(lambda *a, **k: ([], ""))
    )
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    shared_gateway = _merge_gateway()
    service = WebLookupService(repository, shared_gateway)
    captured: dict[str, str] = {}

    def run_alpha() -> None:
        captured["alpha"] = service.lookup("alpha timeout", max_items=5).id

    thread = threading.Thread(target=run_alpha)
    thread.start()
    captured["beta"] = service.lookup("beta timeout", max_items=5).id
    beta_persisted.set()
    thread.join(10)

    assert not thread.is_alive()
    alpha = repository.get(captured["alpha"])
    beta = repository.get(captured["beta"])
    assert alpha is not None and beta is not None
    assert alpha.query_attempts[0]["search_trace"]["ranked_urls"] == [
        "https://alpha.example/1"
    ]
    assert beta.query_attempts[0]["search_trace"]["ranked_urls"] == [
        "https://beta.example/2"
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
            return [
                {
                    "title": "Result",
                    "url": "https://example.com/1",
                    "search_excerpt": query,
                }
            ]

        def warnings(self):
            return []

    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = WebLookupService(WebLookupRepository(database), PlainGateway())

    created = service.lookup("plain lookup", max_items=3)
    restored = WebLookupRepository(database).get(created.id)

    assert restored is not None
    assert "search_trace" not in restored.query_attempts[0]
