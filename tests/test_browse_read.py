from __future__ import annotations

from types import SimpleNamespace

from src.web import browse_read, tool_gateway
from src.web.browse_read import read_browse
from src.web.tool_gateway import GeneralWebGateway


def test_a_private_url_is_never_opened(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("browse must not open a private URL")

    monkeypatch.setattr(browse_read, "_execute", refuse)
    result = read_browse("http://127.0.0.1:8080/admin")
    assert result["ok"] is False
    assert result["error_code"] == "browse_unsafe_url"


def test_a_read_reports_the_final_url_and_size(monkeypatch):
    def run(script, url, timeout, **kwargs):
        assert "https://example.com/story" in script
        return ({"value": {
            "url": "https://example.com/story?from=app",
            "title": "Story",
            "login": False,
            "text": "正文" * 200,
        }}, "")

    monkeypatch.setattr(browse_read, "_execute", run)
    result = read_browse("https://example.com/story", max_chars=1200, timeout=5)
    assert result["ok"] is True
    assert result["url"] == "https://example.com/story?from=app"
    assert result["method"] == "browse"
    assert result["chars"] == len(result["content"]) == 400


def test_a_missing_final_url_is_a_failure_not_the_requested_url(monkeypatch):
    monkeypatch.setattr(browse_read, "_execute", lambda *args, **kwargs: ({
        "value": {"url": "", "title": "T", "login": False, "text": "正文" * 100},
    }, ""))
    result = read_browse("https://example.com/story")
    assert result["ok"] is False
    assert result["error_code"] == "browse_invalid_final_url"
    assert "content" not in result


def test_a_login_wall_with_no_body_is_reported(monkeypatch):
    monkeypatch.setattr(browse_read, "_execute", lambda *args, **kwargs: ({
        "value": {"url": "https://example.com/", "title": "Sign in", "login": True,
                  "text": "请登录"},
    }, ""))
    result = read_browse("https://example.com/")
    assert result["ok"] is False
    assert result["error_code"] == "browse_login_wall"


def test_a_short_budget_does_not_inflate_the_timeout(monkeypatch):
    calls: list[float] = []

    def run(script, url, timeout, **kwargs):
        calls.append(timeout)
        return ({"value": {"url": "https://example.com/", "login": False,
                           "text": "正文" * 100}}, "")

    monkeypatch.setattr(browse_read, "_execute", run)
    assert read_browse("https://example.com/", timeout=0.2)["error_code"] == "browse_no_budget"
    assert calls == []
    read_browse("https://example.com/", timeout=3)
    assert calls and calls[0] <= 3


def test_an_interstitial_is_followed_once(monkeypatch):
    calls: list[str] = []

    def run(script, url, timeout, **kwargs):
        calls.append(script)
        if len(calls) == 1:
            return ({"value": {
                "url": "https://bbs.nga.cn/misc/adpage_insert_2.html"
                       "?https://bbs.nga.cn/read.php?tid=17326655&rand=7",
                "login": False, "text": "",
            }}, "")
        return ({"value": {
            "url": "https://bbs.nga.cn/read.php?tid=17326655",
            "login": False, "text": "主楼正文" * 100,
        }}, "")

    monkeypatch.setattr(browse_read, "_execute", run)
    result = read_browse("https://bbs.nga.cn/read.php?tid=17326655")
    assert result["ok"] is True
    assert len(calls) == 2
    assert "read.php?tid=17326655" in calls[1]


def _failing_read(url: str, **kwargs):
    return SimpleNamespace(
        ok=False, reason="page_read_failed", requested_url=url,
        final_url="", method="", text="", author="",
    )


def _ok_browse(url: str, max_chars: int, timeout: float) -> dict:
    return {"ok": True, "kind": "web_page", "url": url, "method": "browse",
            "content": "浏览器正文" * 100, "title": "T", "chars": 500}


def test_a_failed_static_read_falls_back_to_browse(monkeypatch):
    monkeypatch.setattr(tool_gateway, "_browse_read_available", lambda: True)
    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", _failing_read)
    monkeypatch.setattr(tool_gateway, "_browse_read", _ok_browse)
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://example.com/story", timeout=5
    )
    assert result["ok"] is True
    assert result["method"] == "browse"


def test_http_mode_never_opens_the_browser(monkeypatch):
    monkeypatch.setattr(tool_gateway, "_browse_read_available", lambda: True)
    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", _failing_read)

    def unexpected(*args, **kwargs):
        raise AssertionError("mode=http must not use the browser")

    monkeypatch.setattr(tool_gateway, "_browse_read", unexpected)
    result = GeneralWebGateway(search_strategy="browser_first").read(
        "https://example.com/story", timeout=5, mode="http"
    )
    assert result["ok"] is False


def test_browse_mode_does_not_try_http_first(monkeypatch):
    monkeypatch.setattr(tool_gateway, "_browse_read_available", lambda: True)

    def unexpected(*args, **kwargs):
        raise AssertionError("mode=browse must not run the HTTP reader first")

    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", unexpected)
    monkeypatch.setattr(tool_gateway, "_browse_read", _ok_browse)
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://www.zhihu.com/question/1", timeout=5, mode="browse"
    )
    assert result["method"] == "browse"


def test_browser_first_strategy_reads_with_the_browser_first(monkeypatch):
    monkeypatch.setattr(tool_gateway, "_browse_read_available", lambda: True)

    def unexpected(*args, **kwargs):
        raise AssertionError("browser_first must not read over plain HTTP first")

    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", unexpected)
    monkeypatch.setattr(tool_gateway, "_browse_read", _ok_browse)
    result = GeneralWebGateway(search_strategy="browser_first").read(
        "https://www.miyoushe.com/sr/article/1", timeout=5
    )
    assert result["method"] == "browse"


def test_a_disabled_browser_is_not_used(monkeypatch):
    monkeypatch.setenv("WEB_BROWSE_READ_ENABLED", "0")
    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", _failing_read)

    def unexpected(*args, **kwargs):
        raise AssertionError("an explicit off switch must win")

    monkeypatch.setattr(tool_gateway, "_browse_read", unexpected)
    result = GeneralWebGateway(search_strategy="browser_first").read(
        "https://example.com/story", timeout=5
    )
    assert result["ok"] is False


def test_a_short_static_read_is_upgraded_when_browse_has_more(monkeypatch):
    monkeypatch.setenv("WEB_BROWSE_READ_ENABLED", "1")
    monkeypatch.setattr(tool_gateway, "_browse_read_available", lambda: True)
    monkeypatch.setattr(
        tool_gateway, "fetch_article_read_result",
        lambda url, **kwargs: SimpleNamespace(
            ok=True, reason="", requested_url=url, final_url=url, method="local_html",
            text="导航 首页 登录", author="",
        ),
    )
    monkeypatch.setattr(tool_gateway, "_browse_read", _ok_browse)
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://example.com/story", timeout=5
    )
    assert result["method"] == "browse"
    assert result["chars"] == 500
