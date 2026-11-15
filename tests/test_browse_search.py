from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.web import browse_search
from src.web.tool_gateway import GeneralWebGateway


def test_browser_query_is_data_and_only_public_results_survive(monkeypatch):
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    def run(command, **kwargs):
        script = Path(command[-1]).read_text(encoding="utf-8")
        assert "--rm" in command and "--json" in command
        assert "evil();" not in script
        assert "evil%28%29%3B" in script
        return SimpleNamespace(returncode=0, stdout=json.dumps({"value": {"results": [
            {"title": "WAL", "url": "https://sqlite.org/wal.html"},
            {"title": "private", "url": "http://127.0.0.1/secret"},
        ]}}))
    monkeypatch.setattr(browse_search.subprocess, "run", run)
    rows, error = browse_search.search_browse('SQLite ";evil();', 5, 3)
    assert error == ""
    assert [row["url"] for row in rows] == ["https://sqlite.org/wal.html"]


@pytest.mark.parametrize(
    ("engine", "url_prefix", "selector", "label"),
    [
        ("google", "https://www.google.com/search?", "a:has(h3)", "Google"),
        ("duckduckgo", "https://html.duckduckgo.com/html/?", "a.result__a", "DuckDuckGo"),
        ("bing", "https://www.bing.com/search?", "li.b_algo h2 a", "Bing"),
        ("brave", "https://search.brave.com/search?",
         ".result-content > a:has(.search-snippet-title)", "Brave"),
    ],
)
def test_browser_engines_keep_one_public_result_contract(
    monkeypatch, engine, url_prefix, selector, label
):
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")

    def run(command, **kwargs):
        script = Path(command[-1]).read_text(encoding="utf-8")
        assert url_prefix in script
        assert json.dumps(selector) in script
        assert "ALLOWED_ORIGINS" not in script
        assert "actual.origin" in script
        assert "actual.pathname !== expected.pathname" in script
        if engine == "bing":
            assert "https://cn.bing.com" in script
        return SimpleNamespace(returncode=0, stdout=json.dumps({"value": {"results": [
            {"title": "Official SQLite", "url": "https://sqlite.org/wal.html"},
            {"title": "local", "url": "http://localhost:8000/"},
        ]}}))

    monkeypatch.setattr(browse_search.subprocess, "run", run)
    rows, error = browse_search.search_browse("SQLite WAL", 5, 3, engine=engine)
    assert error == ""
    assert len(rows) == 1
    assert rows[0]["source"] == f"{label} via browse"


def test_browser_engine_env_is_opt_in_and_invalid_choice_fails_closed(monkeypatch):
    monkeypatch.setenv("WEB_BROWSE_SEARCH_ENGINE", "DuckDuckGo")
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: None)
    assert browse_search.search_browse("WAL", 5, 3) == ([], "browse:cli_unavailable")
    monkeypatch.setenv("WEB_BROWSE_SEARCH_ENGINE", "unrecognized")
    assert browse_search.search_browse("WAL", 5, 3) == ([], "browse:invalid_engine")


def test_bing_wrapper_is_unwrapped_before_citation():
    encoded = base64.urlsafe_b64encode(b"https://www.postgresql.org/docs/current/transaction-iso.html").decode()
    wrapper = f"https://www.bing.com/ck/a?u=a1{encoded}&ntb=1"
    assert browse_search._result_url(wrapper, "bing") == (
        "https://www.postgresql.org/docs/current/transaction-iso.html"
    )
    assert browse_search._result_url("https://www.bing.com/ck/a?u=invalid", "bing") == ""
    private = base64.urlsafe_b64encode(b"http://127.0.0.1:8080/secret").decode()
    assert browse_search._result_url(f"https://www.bing.com/ck/a?u=a1{private}", "bing") == ""


def test_browser_challenge_stops_provider_fallback(monkeypatch):
    monkeypatch.setattr(GeneralWebGateway, "_search_browse", staticmethod(
        lambda *args: ([], "browse:human_action_required")))
    monkeypatch.setattr(GeneralWebGateway, "_search_bing_rss", staticmethod(
        lambda *args: (_ for _ in ()).throw(AssertionError("unexpected fallback"))))
    result = GeneralWebGateway(search_strategy="browser_first").search_exact("SQLite WAL")
    assert result["results"] == []
    assert result["providers_attempted"] == ["browse"]
    assert "browse:human_action_required" in result["provider_errors"]


def test_browser_results_use_existing_domain_filter(monkeypatch):
    monkeypatch.setattr(GeneralWebGateway, "_search_browse", staticmethod(lambda *args: ([
        {"title": "WAL", "url": "https://sqlite.org/wal.html", "snippet": ""},
        {"title": "unrelated", "url": "https://example.org/", "snippet": ""},
    ], "")))
    result = GeneralWebGateway(search_strategy="browser_first").search_exact("SQLite WAL site:sqlite.org")
    assert [row["url"] for row in result["results"]] == ["https://sqlite.org/wal.html"]
    assert result["domain_filtered_count"] == 1
