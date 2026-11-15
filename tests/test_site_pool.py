"""Site-pool routing, result validity and the browse_sites gateway strategy."""

from __future__ import annotations

from src.web import browse_search, site_pool
from src.web.tool_gateway import GeneralWebGateway, _merge_site_results


def test_question_shape_selects_relevant_sites():
    keys = [site.key for site in site_pool.select_sites(
        "FastAPI 报错 database is locked", include_unverified=True)]
    assert keys[:2] == ["stackoverflow", "github"]

    keys = [site.key for site in site_pool.select_sites("FastAPI 报错 database is locked")]
    assert keys[0] == "github"

    keys = [site.key for site in site_pool.select_sites(
        "OpenCode 和 Codex 哪个更适合大型项目", include_unverified=True)]
    assert keys[0] == "google"
    assert "reddit" in keys and "hn" in keys

    keys = [site.key for site in site_pool.select_sites(
        "OpenCode 和 Codex 哪个更适合大型项目")]
    assert keys[0] == "google"

    keys = [site.key for site in site_pool.select_sites("SQLite 和 PostgreSQL 怎么选")]
    assert keys[0] == "google"

    keys = [site.key for site in site_pool.select_sites("随便聊聊今天的天气")]
    assert keys[0] == "google"


def test_a_domain_word_outranks_a_generic_intent_word():
    # "推荐" is a generic intent word; the game community is still the source.
    keys = [site.key for site in site_pool.select_sites(
        "星铁虚构叙事配队推荐", include_unverified=True)]
    assert keys[0] in {"miyoushe", "nga"}

    keys = [site.key for site in site_pool.select_sites(
        "校招岗位推荐", include_unverified=True)]
    assert keys[0] == "nowcoder"

    keys = [site.key for site in site_pool.select_sites(
        "RTX 5060 玩某款游戏怎么样", include_unverified=True)]
    assert keys[0] == "steam"


def test_short_ascii_words_match_as_words_not_fragments():
    # "api" inside "FastAPI" must not route a deployment question to a model hub.
    keys = [site.key for site in site_pool.select_sites(
        "FastAPI 应用如何部署", include_unverified=True)]
    assert "huggingface" not in keys
    assert keys[0] == "github"

    keys = [site.key for site in site_pool.select_sites(
        "这个 agent 框架值得用吗", include_unverified=True)]
    assert keys[0] == "huggingface"


def test_only_sites_with_real_browser_evidence_are_routed(monkeypatch):
    keys = [site.key for site in site_pool.select_sites("星铁虚构叙事配队推荐")]
    assert keys[0] == "miyoushe"          # verified after login + page adapters
    assert "nga" not in keys              # still failing: only footer links
    assert all(site_pool._BY_KEY[key].default_enabled for key in keys)

    monkeypatch.setenv("WEB_SITE_POOL_EXTRA_SITES", "nga")
    keys = [site.key for site in site_pool.select_sites("星铁虚构叙事配队推荐")]
    assert keys[:2] == ["miyoushe", "nga"]


def test_every_default_site_can_recognise_its_results():
    for site in site_pool.SITES:
        if site.default_enabled:
            assert site.verified, site.key


def test_selection_is_bounded_and_deduplicated(monkeypatch):
    monkeypatch.setenv("WEB_SITE_POOL_LIMIT", "2")
    keys = [site.key for site in site_pool.select_sites("报错 error exception")]
    assert len(keys) == 2
    assert len(set(keys)) == 2


def test_a_game_question_uses_the_matching_miyoushe_search_page():
    miyoushe = site_pool._BY_KEY["miyoushe"]
    assert miyoushe.search_url("流萤 配队").startswith(
        "https://www.miyoushe.com/sr/search?keyword="
    )
    assert miyoushe.search_url("原神 纳西妲 配队").startswith(
        "https://www.miyoushe.com/ys/search?keyword="
    )
    assert miyoushe.search_url("绝区零 配队").startswith(
        "https://www.miyoushe.com/zzz/search?keyword="
    )


def test_a_site_without_a_result_rule_is_not_routed(monkeypatch):
    bare = site_pool.SiteProfile(
        "bare", "Bare", "search", "https://ex.com/", "https://ex.com/s?q={q}"
    )
    assert bare.verified is False
    monkeypatch.setitem(site_pool._BY_KEY, "bare", bare)
    monkeypatch.setattr(site_pool, "_DOMAIN_ROUTES", ())
    monkeypatch.setattr(site_pool, "_INTENT_ROUTES", ((("foo",), ("bare", "google")),))

    assert "bare" not in [site.key for site in site_pool.select_sites("foo")]
    keys = [site.key for site in site_pool.select_sites("foo", include_unverified=True)]
    assert keys[0] == "bare"


def test_site_search_url_encodes_the_query():
    github = next(site for site in site_pool.SITES if site.key == "github")
    url = github.search_url("database is locked & busy")
    assert url.startswith("https://github.com/search?q=")
    assert "database+is+locked" in url
    assert "&type=issues" in url
    assert " " not in url


def test_navigation_and_login_links_are_not_results():
    pattern = next(site for site in site_pool.SITES if site.key == "juejin").result_pattern
    rows = browse_search._valid_rows(
        [
            {"title": "稀土掘金 - 首页", "url": "https://juejin.cn/"},
            {"title": "登录掘金", "url": "https://juejin.cn/login"},
            {"title": "SQLite WAL 并发实践", "url": "https://juejin.cn/post/7287976064725663807"},
        ],
        5,
        source="juejin",
        pattern=pattern,
    )
    assert [row["url"] for row in rows] == [
        "https://juejin.cn/post/7287976064725663807"
    ]


def test_a_search_engine_never_returns_its_own_navigation():
    rows = browse_search._valid_rows(
        [
            {"title": "Google 图片", "url": "https://www.google.com/imghp"},
            {"title": "SQLite WAL", "url": "https://sqlite.org/wal.html"},
        ],
        5,
        source="google",
        own_hosts=("www.google.com",),
    )
    assert [row["url"] for row in rows] == ["https://sqlite.org/wal.html"]


def _envelope(results, *, blocked=False, login=False):
    return (
        {
            "value": {
                "blocked": blocked,
                "login": login,
                "url": "https://juejin.cn/search?query=wal",
                "results": results,
            },
            "aftermath": {},
        },
        "",
    )


def test_a_page_of_only_navigation_is_not_a_successful_search(monkeypatch):
    monkeypatch.setattr(
        browse_search,
        "_execute",
        lambda *args, **kwargs: _envelope(
            [{"title": "稀土掘金 - 首页", "url": "https://juejin.cn/"}]
        ),
    )
    pattern = next(site for site in site_pool.SITES if site.key == "juejin").result_pattern
    rows, error, meta = browse_search.search_browse_at(
        "https://juejin.cn/search?query=wal", 5, 3, pattern=pattern
    )

    assert rows == []
    assert error == "browse:no_valid_results"
    assert meta["status"] == "browse:no_valid_results"
    assert meta["page_results"] == 1


def test_one_real_result_is_reported_as_ok(monkeypatch):
    monkeypatch.setattr(
        browse_search,
        "_execute",
        lambda *args, **kwargs: _envelope(
            [
                {"title": "稀土掘金 - 首页", "url": "https://juejin.cn/"},
                {"title": "SQLite WAL 并发实践", "url": "https://juejin.cn/post/728"},
            ]
        ),
    )
    pattern = next(site for site in site_pool.SITES if site.key == "juejin").result_pattern
    rows, error, meta = browse_search.search_browse_at(
        "https://juejin.cn/search?query=wal", 5, 3, pattern=pattern
    )

    assert error == ""
    assert [row["url"] for row in rows] == ["https://juejin.cn/post/728"]
    assert meta["status"] == "ok"
    assert meta["page_results"] == 2


def test_a_client_rendered_site_waits_for_its_result_container(monkeypatch):
    nowcoder = next(site for site in site_pool.SITES if site.key == "nowcoder")
    assert nowcoder.wait_selector == nowcoder.result_selector
    assert "feed/main/detail" in nowcoder.result_selector

    explicit = site_pool.SiteProfile(
        "x", "X", "domain", "https://x.example/", "https://x.example/s?q={q}",
        result_selector=".hit", wait_for=".hit-list",
    )
    assert explicit.wait_selector == ".hit-list"

    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    captured: list[str] = []

    def run(command, **kwargs):
        captured.clear()
        from pathlib import Path
        import json
        captured.append(Path(command[-1]).read_text(encoding="utf-8"))
        return __import__("types").SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"value": {"url": "https://x.example/s", "results": []}}),
        )

    monkeypatch.setattr(browse_search.subprocess, "run", run)
    browse_search.search_browse_at(
        "https://x.example/s?q=a", 5, 8, selector=".hit", wait_for=".hit-list"
    )
    script = captured[0]
    assert '".hit-list"' in script
    assert "WAIT_FOR_SELECTOR" not in script
    assert "WAIT_FOR_MS" not in script


def test_the_gateway_passes_the_wait_selector(monkeypatch):
    seen: dict[str, str] = {}

    def fake(url, limit, timeout, **kwargs):
        seen.update(kwargs)
        return [], "browse:no_results", {"status": "browse:no_results", "seconds": 1.0}

    monkeypatch.setattr(browse_search, "search_browse_at", fake)
    _gateway(monkeypatch).search_exact("RTX 5060 玩某款游戏怎么样")
    assert seen["wait_for"] == "a.search_result_row"


def test_the_site_selector_is_parameterized_not_executed(monkeypatch):
    captured: dict[str, str] = {}

    def run(command, **kwargs):
        from pathlib import Path
        from types import SimpleNamespace
        import json

        captured["script"] = Path(command[-1]).read_text(encoding="utf-8")
        return SimpleNamespace(
            returncode=0, stdout=json.dumps(_envelope([])[0])
        )

    monkeypatch.setattr(browse_search.shutil, "which", lambda name: "browse")
    monkeypatch.setattr(browse_search.subprocess, "run", run)

    browse_search.search_browse_at(
        "https://www.bing.com/search?q=wal", 5, 3, selector="li.b_algo h2 a"
    )
    assert '"li.b_algo h2 a"' in captured["script"]
    assert "RESULT_SELECTOR" not in captured["script"]


def _gateway(monkeypatch):
    monkeypatch.setenv("WEB_SITE_POOL_LIMIT", "2")
    monkeypatch.setenv("WEB_SITE_POOL_TOTAL_SECONDS", "8")
    monkeypatch.setenv("WEB_SITE_POOL_EXTRA_SITES", "stackoverflow")
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "0")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "0")
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: False)
    return GeneralWebGateway(search_strategy="browse_sites")


def test_browse_sites_merges_selected_sites_and_records_outcomes(monkeypatch):
    calls: list[str] = []

    def fake(url, limit, timeout, **kwargs):
        calls.append(url)
        host = "github.com" if "github" in url else "stackoverflow.com"
        return (
            [{"title": f"{host} answer", "url": f"https://{host}/q/1", "snippet": ""}],
            "",
            {"status": "ok", "seconds": 1.2, "page_results": 4},
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
    assert [item["page_results"] for item in result["site_outcomes"]] == [4, 4]


def test_a_login_wall_on_one_site_does_not_stop_the_others(monkeypatch):
    def fake(url, limit, timeout, **kwargs):
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
    def empty(url, limit, timeout, **kwargs):
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


def test_a_normal_search_is_not_mistaken_for_a_verification_page():
    # A word inside the query string is not a challenge.
    assert browse_search._is_verification_page(
        "https://www.nowcoder.com/search?query=coding+challenge", "牛客搜索"
    ) is False
    assert browse_search._is_verification_page(
        "https://www.bing.com/search?q=captcha+challenge", "Bing"
    ) is False
    # A verification wall is detected by path or title.
    assert browse_search._is_verification_page(
        "https://stackoverflow.com/nocaptcha?s=abc", "Human verification - Stack Overflow"
    ) is True
    assert browse_search._is_verification_page(
        "https://example.com/verify-human", ""
    ) is True


def test_the_route_report_separates_candidates_from_what_runs():
    route = site_pool.describe_route("星铁虚构叙事配队推荐")

    assert route["candidates"][:2] == ["miyoushe", "nga"]
    assert route["enabled"][0] == "miyoushe"
    assert "nga" in route["skipped"] and "reddit" in route["skipped"]
    assert all(key not in route["skipped"] for key in route["enabled"])
    assert set(route["enabled"]) | set(route["skipped"]) | set(route["trimmed"]) == set(
        route["candidates"]
    )


def test_results_come_from_several_sites_not_just_the_first(monkeypatch):
    def fake(url, limit, timeout, **kwargs):
        host = "stackoverflow.com" if "stackoverflow" in url else "github.com"
        return (
            [{"title": f"{host} {i}", "url": f"https://{host}/q/{i}", "snippet": ""}
             for i in range(1, 6)],
            "",
            {"status": "ok", "seconds": 1.0},
        )

    monkeypatch.setattr(browse_search, "search_browse_at", fake)
    result = _gateway(monkeypatch).search_exact("FastAPI 报错 database is locked")

    urls = [row["url"] for row in result["results"]]
    assert len(urls) == 5
    assert urls[:4] == [
        "https://stackoverflow.com/q/1",
        "https://github.com/q/1",
        "https://stackoverflow.com/q/2",
        "https://github.com/q/2",
    ]
    assert len({url.split("/")[2] for url in urls}) == 2


def test_one_productive_site_still_fills_the_answer(monkeypatch):
    def fake(url, limit, timeout, **kwargs):
        if "github" in url:
            return [], "browse:no_results", {"status": "browse:no_results", "seconds": 1.0}
        return (
            [{"title": f"so {i}", "url": f"https://stackoverflow.com/q/{i}", "snippet": ""}
             for i in range(1, 6)],
            "",
            {"status": "ok", "seconds": 1.0},
        )

    monkeypatch.setattr(browse_search, "search_browse_at", fake)
    result = _gateway(monkeypatch).search_exact("FastAPI 报错 database is locked")

    assert [row["url"] for row in result["results"]] == [
        f"https://stackoverflow.com/q/{i}" for i in range(1, 6)
    ]


def test_the_same_page_with_and_without_www_is_one_result():
    def row(url):
        return {"title": "SQLite WAL", "url": url, "snippet": ""}

    merged = _merge_site_results(
        [
            ("google", [row("https://www.sqlite.org/wal.html"), row("https://sqlite.org/a")]),
            ("brave", [row("https://sqlite.org/wal.html"), row("https://sqlite.org/b")]),
        ],
        5,
    )
    assert [item["url"] for item in merged] == [
        "https://www.sqlite.org/wal.html",
        "https://sqlite.org/b",
        "https://sqlite.org/a",
    ]


def test_every_selected_site_is_visited_even_after_a_full_page(monkeypatch):
    calls: list[str] = []

    def fake(url, limit, timeout, **kwargs):
        calls.append(url)
        return (
            [{"title": f"{len(calls)}", "url": f"https://stackoverflow.com/q/{len(calls)}", "snippet": ""}],
            "",
            {"status": "ok", "seconds": 1.0},
        )

    monkeypatch.setattr(browse_search, "search_browse_at", fake)
    result = _gateway(monkeypatch).search_exact("FastAPI 报错 database is locked")

    assert len(calls) == 2
    assert len(result["site_outcomes"]) == 2


def test_the_pool_failure_still_leaves_time_for_the_fallback(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("src.web.tool_gateway.time.monotonic", lambda: clock["now"])
    monkeypatch.setenv("WEB_SITE_POOL_TOTAL_SECONDS", "6")
    monkeypatch.setenv("WEB_SEARCH_FALLBACK_RESERVE_SECONDS", "4")
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "0")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "0")
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: True)
    gateway = GeneralWebGateway(search_strategy="browse_sites")
    seen: dict[str, float] = {}

    def pool(query, limit, timeout):
        seen["pool"] = timeout
        clock["now"] += timeout  # a slow pool uses its whole budget
        return [], "browse:no_results"

    def searxng(query, limit, timeout):
        seen["searxng"] = timeout
        return [{"title": "fallback", "url": "https://example.org/x", "snippet": ""}], ""

    monkeypatch.setattr(gateway, "_search_browse_sites", pool)
    monkeypatch.setattr(gateway, "_search_searxng", searxng)
    result = gateway.search_exact("SQLite 和 PostgreSQL 怎么选")

    assert seen["pool"] == 6
    assert seen["searxng"] >= 2
    assert [row["url"] for row in result["results"]] == ["https://example.org/x"]


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
