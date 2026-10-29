"""D2: DuckDuckGo first, Bing only as a fallback.

Search-1 measured that the first result decides whether the caller can answer,
and that DuckDuckGo's own first result was the only one that answered those
questions. These tests pin the contract that makes the switch safe: one request
when the first engine answers, and a real fallback when it does not.
"""

from __future__ import annotations

import pytest

from src.web import tool_gateway
from src.web.tool_gateway import GeneralWebGateway


def _row(title: str, url: str, snippet: str = "") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet, "source": "test"}


@pytest.fixture(autouse=True)
def _no_searxng(monkeypatch):
    monkeypatch.setattr(tool_gateway, "searxng_enabled", lambda: False)


def _patch(monkeypatch, bing, ddg):
    monkeypatch.setattr(
        GeneralWebGateway, "_search_bing_rss", staticmethod(lambda *a, **k: bing())
    )
    monkeypatch.setattr(
        GeneralWebGateway, "_search_duckduckgo", staticmethod(lambda *a, **k: ddg())
    )


def test_ddg_first_never_asks_the_second_engine_when_the_first_answers(monkeypatch):
    calls: list[str] = []

    def ddg():
        calls.append("ddg")
        return [_row("hosted answer", "https://a.example/1")], ""

    def bing():
        calls.append("bing")
        return [_row("homepage", "https://b.example/2")], ""

    _patch(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="ddg_first").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert calls == ["ddg"]
    assert [item["url"] for item in payload["results"]] == ["https://a.example/1"]
    assert payload["providers_attempted"] == ["duckduckgo_html"]
    assert payload["fallback_used"] is False
    assert payload["search_strategy"] == "ddg_first"


def test_ddg_first_falls_back_to_bing_when_ddg_returns_nothing(monkeypatch):
    calls: list[str] = []

    def ddg():
        calls.append("ddg")
        return [], "duckduckgo_html:URLError:<urlopen error timed out>"

    def bing():
        calls.append("bing")
        return [_row("fallback answer", "https://b.example/2")], ""

    _patch(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="ddg_first").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert calls == ["ddg", "bing"]
    assert [item["url"] for item in payload["results"]] == ["https://b.example/2"]
    assert payload["fallback_used"] is True
    assert payload["providers_attempted"] == ["duckduckgo_html", "bing_rss"]
    assert any("timed out" in error for error in payload["provider_errors"])
    assert payload["status"] == "ok"


def test_fallback_used_is_true_even_when_the_fallback_also_returns_nothing(monkeypatch):
    """A consulted fallback is a fallback, even if the whole search then fails."""

    calls: list[str] = []

    def ddg():
        calls.append("ddg")
        return [], "duckduckgo_html:URLError:<urlopen error timed out>"

    def bing():
        calls.append("bing")
        return [], "bing_rss:http_status:503"

    _patch(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="ddg_first").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert calls == ["ddg", "bing"]
    assert payload["status"] == "unavailable"
    assert payload["fallback_used"] is True
    assert payload["providers_attempted"] == ["duckduckgo_html", "bing_rss"]
    assert payload["provider_counts"] == {"duckduckgo_html": 0, "bing_rss": 0}


def test_ddg_first_skips_a_disabled_primary_and_still_answers(monkeypatch):
    calls: list[str] = []
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "false")

    def ddg():
        calls.append("ddg")
        return [_row("should not be used", "https://a.example/1")], ""

    def bing():
        calls.append("bing")
        return [_row("fallback answer", "https://b.example/2")], ""

    _patch(monkeypatch, bing, ddg)

    payload = GeneralWebGateway(search_strategy="ddg_first").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert calls == ["bing"]
    assert payload["providers_attempted"] == ["bing_rss"]
    assert payload["fallback_used"] is True
    # The disabled engine is still reported, so a single-engine answer is never
    # mistaken for a merge that found only one source.
    assert any("provider_disabled" in error for error in payload["provider_errors"])


def test_ddg_first_reports_unavailable_only_when_every_provider_failed(monkeypatch):
    _patch(
        monkeypatch,
        bing=lambda: ([], "bing_rss:http_status:503"),
        ddg=lambda: ([], "duckduckgo_html:URLError:<urlopen error timed out>"),
    )

    payload = GeneralWebGateway(search_strategy="ddg_first").search_exact(
        "python asyncio timeout", max_results=5
    )

    assert payload["results"] == []
    assert payload["status"] == "unavailable"
    assert len(payload["provider_errors"]) == 2
    assert payload["providers_attempted"] == ["duckduckgo_html", "bing_rss"]


def test_the_strategy_can_be_selected_from_the_environment(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_STRATEGY", "ddg_first")

    assert GeneralWebGateway().search_strategy == "ddg_first"


def test_an_unknown_environment_strategy_fails_loudly(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_STRATEGY", "ddg-first")

    with pytest.raises(ValueError, match="unknown WEB_SEARCH_STRATEGY"):
        GeneralWebGateway()


def test_the_production_gateway_class_honours_the_environment_strategy(monkeypatch):
    """The chat path builds this class with no strategy argument.

    If someone later pins ``search_strategy=`` on that constructor call, the
    deployment switch would silently stop working while every unit test on the
    base class kept passing.
    """

    from src.web.persistent_tool_gateway import PersistentGeneralWebGateway

    class StubSnapshotService:
        def search_repository(self, *args, **kwargs):
            return {"ok": True, "result_count": 0}

    monkeypatch.setenv("WEB_SEARCH_STRATEGY", "ddg_first")

    gateway = PersistentGeneralWebGateway(StubSnapshotService())

    assert gateway.search_strategy == "ddg_first"


def test_no_environment_setting_keeps_the_fallback(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_STRATEGY", raising=False)

    assert GeneralWebGateway().search_strategy == "fallback"
