from __future__ import annotations

import json
import sys

from src.web import browse_search
from src.web.tool_gateway import GeneralWebGateway
from tests.browse_mcp_fixture import execute_request, execute_response


def test_browser_query_is_data_and_only_public_results_survive(monkeypatch):
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    def run(command, **kwargs):
        script = execute_request(kwargs["input"])["code"]
        assert command == ["browse", "mcp"]
        assert execute_request(kwargs["input"])["timeoutMs"] == 3000
        assert "await page.close()" in script
        assert "evil();" not in script
        assert "evil%28%29%3B" in script
        return execute_response({"results": [
            {"title": "WAL", "url": "https://sqlite.org/wal.html"},
            {"title": "private", "url": "http://127.0.0.1/secret"},
        ]})
    monkeypatch.setattr(browse_search, "_run_mcp", run)
    rows, error = browse_search.search_browse('SQLite ";evil();', 5, 3)
    assert error == ""
    assert [row["url"] for row in rows] == ["https://sqlite.org/wal.html"]


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


def test_each_engine_uses_its_own_endpoint_selector_and_origin(monkeypatch):
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    captured: list[str] = []

    def run(command, **kwargs):
        captured.clear()
        captured.append(execute_request(kwargs["input"])["code"])
        return execute_response({"results": [
            {"title": "SQLite WAL", "url": "https://sqlite.org/wal.html"},
        ]})

    monkeypatch.setattr(browse_search, "_run_mcp", run)

    for engine, endpoint, selector, origin in [
        ("google", "https://www.google.com/search?", "a:has(h3)", "https://www.google.com"),
        ("duckduckgo", "https://html.duckduckgo.com/html/?", "a.result__a",
         "https://html.duckduckgo.com"),
        ("bing", "https://www.bing.com/search?", "li.b_algo h2 a", "https://cn.bing.com"),
        ("brave", "https://search.brave.com/search?",
         ".result-content > a:has(.search-snippet-title)", "https://search.brave.com"),
    ]:
        rows, error = browse_search.search_browse("SQLite WAL", 5, 3, engine=engine)
        assert error == ""
        assert len(rows) == 1
        script = captured[0]
        assert endpoint in script
        assert json.dumps(selector) in script
        assert origin in script
        # Parameter substitution must not leave the placeholder behind.
        assert "ALLOWED_ORIGINS" not in script
        assert "RESULT_SELECTOR" not in script


def test_an_unknown_engine_fails_closed(monkeypatch):
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    assert browse_search.search_browse("WAL", 5, 3, engine="exa") == (
        [], "browse:invalid_engine"
    )


def test_the_engine_choice_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("WEB_BROWSE_SEARCH_ENGINE", "Brave")
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")

    def run(command, **kwargs):
        script = execute_request(kwargs["input"])["code"]
        assert "https://search.brave.com/search?" in script
        return execute_response({"results": []})

    monkeypatch.setattr(browse_search, "_run_mcp", run)
    assert browse_search.search_browse("WAL", 5, 3) == ([], "browse:no_results")


def test_a_bing_redirect_wrapper_is_unwrapped_before_citation():
    import base64

    encoded = base64.urlsafe_b64encode(
        b"https://www.postgresql.org/docs/current/transaction-iso.html"
    ).decode()
    wrapper = f"https://www.bing.com/ck/a?u=a1{encoded}&ntb=1"
    assert browse_search._result_url(wrapper, "bing") == (
        "https://www.postgresql.org/docs/current/transaction-iso.html"
    )
    assert browse_search._result_url("https://www.bing.com/ck/a?u=invalid", "bing") == ""
    private = base64.urlsafe_b64encode(b"http://127.0.0.1:8080/secret").decode()
    assert browse_search._result_url(f"https://www.bing.com/ck/a?u=a1{private}", "bing") == ""


def test_stdio_challenge_is_reported_without_using_results(monkeypatch):
    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    monkeypatch.setattr(
        browse_search,
        "_run_mcp",
        lambda *args, **kwargs: execute_response(
            {"results": [{"title": "unexpected", "url": "https://example.com/article"}]},
            suffix="\n\nChallenge: human action required",
        ),
    )
    assert browse_search.search_browse("WAL", 5, 3) == ([], "browse:human_action_required")


def test_stdio_stays_open_for_a_delayed_browser_response():
    child = """
import json
import sys
from threading import Timer

sys.stdin.readline()
print(json.dumps({"id": 1}), flush=True)
reply = Timer(0.05, lambda: print(json.dumps({"id": 2, "result": {"ok": True}}), flush=True))
reply.daemon = True
reply.start()
sys.stdin.read()
"""
    response = browse_search._run_mcp([sys.executable, "-c", child], input="start\n", timeout=3)
    assert json.loads(response)["result"] == {"ok": True}
