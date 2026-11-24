from __future__ import annotations

from types import SimpleNamespace

from src.web import browse_read, tool_gateway
from src.web.browse_read import read_browse
from src.web.tool_gateway import GeneralWebGateway


def test_a_private_url_is_never_opened(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("browse must not open a private URL")

    monkeypatch.setattr(browse_read, "_execute", refuse)
    assert read_browse("http://127.0.0.1:8080/admin") is None
    assert read_browse("file:///etc/passwd") is None


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
    assert result is not None
    assert result["url"] == "https://example.com/story?from=app"
    assert result["method"] == "browse"
    assert result["chars"] == len(result["content"]) == 400


def test_a_login_wall_with_no_body_is_not_a_read(monkeypatch):
    monkeypatch.setattr(browse_read, "_execute", lambda *args, **kwargs: ({
        "value": {"url": "https://example.com/", "title": "Sign in", "login": True,
                  "text": "请登录"},
    }, ""))
    assert read_browse("https://example.com/") is None


def _failing_read(url: str, **kwargs):
    return SimpleNamespace(
        ok=False, reason="page_read_failed", requested_url=url,
        final_url="", method="", text="", author="",
    )


def test_a_failed_static_read_falls_back_to_browse(monkeypatch):
    monkeypatch.setenv("WEB_BROWSE_READ_ENABLED", "1")
    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", _failing_read)
    monkeypatch.setattr(
        tool_gateway, "_browse_read",
        lambda url, max_chars, timeout: {
            "ok": True, "kind": "web_page", "url": url, "method": "browse",
            "content": "浏览器正文" * 100, "title": "T", "chars": 500,
        },
    )
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://example.com/story", timeout=5
    )
    assert result["ok"] is True
    assert result["method"] == "browse"


def test_browse_read_stays_off_by_default(monkeypatch):
    monkeypatch.delenv("WEB_BROWSE_READ_ENABLED", raising=False)
    monkeypatch.setattr(tool_gateway, "fetch_article_read_result", _failing_read)

    def unexpected(*args, **kwargs):
        raise AssertionError("browse read must stay off for the fallback strategy")

    monkeypatch.setattr(tool_gateway, "_browse_read", unexpected)
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://example.com/story", timeout=5
    )
    assert result["ok"] is False
    assert result["error_code"]


def test_a_short_static_read_is_upgraded_when_browse_has_more(monkeypatch):
    monkeypatch.setenv("WEB_BROWSE_READ_ENABLED", "true")
    monkeypatch.setattr(
        tool_gateway, "fetch_article_read_result",
        lambda url, **kwargs: SimpleNamespace(
            ok=True, reason="", requested_url=url, final_url=url, method="local_html",
            text="导航 首页 登录", author="",
        ),
    )
    monkeypatch.setattr(
        tool_gateway, "_browse_read",
        lambda url, max_chars, timeout: {
            "ok": True, "kind": "web_page", "url": url, "method": "browse",
            "content": "真正正文" * 100, "title": "T", "chars": 400,
        },
    )
    result = GeneralWebGateway(search_strategy="fallback").read(
        "https://example.com/story", timeout=5
    )
    assert result["method"] == "browse"
    assert result["chars"] == 400
