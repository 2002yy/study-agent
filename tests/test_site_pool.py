"""Site-pool routing and the browse_sites gateway strategy."""

from __future__ import annotations

from src.web import browse_search, site_pool
from src.web.tool_gateway import GeneralWebGateway


def test_question_shape_selects_relevant_sites():
    keys = [site.key for site in site_pool.select_sites("FastAPI 报错 database is locked")]
    assert keys[:2] == ["stackoverflow", "github"]

    keys = [site.key for site in site_pool.select_sites("OpenCode 和 Codex 哪个更适合大型项目")]
    assert keys[0] == "reddit"

    keys = [site.key for site in site_pool.select_sites("SQLite 和 PostgreSQL 怎么选")]
    assert keys[0] in {"reddit", "google"}

    keys = [site.key for site in site_pool.select_sites("随便聊聊今天的天气")]
    assert keys[0] == "google"


def test_selection_is_bounded_and_deduplicated(monkeypatch):
    monkeypatch.setenv("WEB_SITE_POOL_LIMIT", "2")
    keys = [site.key for site in site_pool.select_sites("报错 error exception")]
    assert len(keys) == 2
    assert len(set(keys)) == 2


def test_site_search_url_encodes_the_query():
    github = next(site for site in site_pool.SITES if site.key == "github")
    url = github.search_url("database is locked & busy")
    assert url.startswith("https://github.com/search?q=")
    assert "database+is+locked" in url
    assert "&type=issues" in url
    assert " " not in url


def _gateway(monkeypatch):
    monkeypatch.setenv("WEB_SITE_POOL_LIMIT", "2")
    monkeypatch.setenv("WEB_SITE_POOL_TOTAL_SECONDS", "8")
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "0")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "0")
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: False)
    return GeneralWebGateway(search_strategy="browse_sites")


def test_browse_sites_merges_selected_sites_and_records_outcomes(monkeypatch):
    calls: list[str] = []

    def fake(url, limit, timeout, source=""):
        calls.append(url)
        host = "github.com" if "github" in url else "stackoverflow.com"
        return (
            [{"title": f"{host} answer", "url": f"https://{host}/q/1", "snippet": ""}],
            "",
            {"status": "ok", "seconds": 1.2},
        )

    monkeypatch.setattr(browse_search, "search_browse_at", fake)
    result = _gateway(monkeypatch).search_exact("FastAPI 报错 database is locked")

    assert [row["url"] for row in result["results"]] == [
        "https://stackoverflow.com/q/1",
        "https://github.com/q/1",
    ]
    assert result["providers_attempted"] == ["browse_sites"]
    assert [item["site"] for item in result["site_outcomes"]] == [
        "stackoverflow",
        "github",
    ]
    assert all(item["status"] == "ok" for item in result["site_outcomes"])


def test_a_login_wall_on_one_site_does_not_stop_the_others(monkeypatch):
    def fake(url, limit, timeout, source=""):
        if "github" in url:
            return [], "browse:login_required", {"status": "browse:login_required", "seconds": 1.0}
        return (
            [{"title": "SO answer", "url": "https://stackoverflow.com/q/2", "snippet": ""}],
            "",
            {"status": "ok", "seconds": 1.0},
        )

    monkeypatch.setattr(browse_search, "search_browse_at", fake)
    result = _gateway(monkeypatch).search_exact("FastAPI 报错 traceback")

    assert [row["url"] for row in result["results"]] == ["https://stackoverflow.com/q/2"]
    statuses = {item["site"]: item["status"] for item in result["site_outcomes"]}
    assert statuses["github"] == "browse:login_required"


def test_no_site_result_still_falls_back(monkeypatch):
    def empty(url, limit, timeout, source=""):
        return [], "browse:no_results", {"status": "browse:no_results", "seconds": 1.0}

    monkeypatch.setattr(browse_search, "search_browse_at", empty)
    gateway = _gateway(monkeypatch)
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: True)
    monkeypatch.setattr(
        gateway,
        "_search_searxng",
        lambda *args: ([{"title": "fallback", "url": "https://example.org/x", "snippet": ""}], ""),
    )
    result = gateway.search_exact("FastAPI 报错 traceback")

    assert [row["url"] for row in result["results"]] == ["https://example.org/x"]
    assert result["providers_attempted"] == ["browse_sites", "searxng"]
    assert "browse:no_results" in result["provider_errors"]


def test_site_pool_filters_non_public_results():
    rows = browse_search._public_rows(
        [
            {"title": "private", "url": "http://127.0.0.1/secret"},
            {"title": "public page", "url": "https://reddit.com/r/x"},
        ],
        5,
        source="site via browse",
    )
    assert [row["url"] for row in rows] == ["https://reddit.com/r/x"]
