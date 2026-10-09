"""Tests for the opt-in Tavily provider (B-Search-2B9-D)."""
from __future__ import annotations

import json

import src.news.search_sources.tavily_source as tv


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("WEB_ENABLE_TAVILY", "true")
    assert tv.tavily_enabled() is False
    assert tv.search_tavily("q") == []
    assert tv.get_last_tavily_error() == "missing_api_key"


def test_disabled_unless_flag(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.delenv("WEB_ENABLE_TAVILY", raising=False)
    assert tv.tavily_enabled() is False


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_parses_results_and_counts_calls(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv("WEB_ENABLE_TAVILY", "true")
    body = json.dumps({"results": [
        {"title": "Train interrupts", "url": "https://wiki.factorio.com/Train_interrupts", "content": "..."},
        {"title": "", "url": "https://x", "content": "dropped: no title"},
    ]}).encode("utf-8")
    monkeypatch.setattr(tv, "urlopen", lambda req, timeout=0: _Resp(body))
    before = tv.get_tavily_call_count()
    out = tv.search_tavily("train interrupts", max_results=5)
    assert [r["url"] for r in out] == ["https://wiki.factorio.com/Train_interrupts"]
    assert out[0]["source"] == "Tavily"
    assert tv.get_tavily_call_count() == before + 1


def test_request_failure_is_diagnosable(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setenv("WEB_ENABLE_TAVILY", "true")

    def boom(req, timeout=0):
        raise TimeoutError("slow")

    monkeypatch.setattr(tv, "urlopen", boom)
    assert tv.search_tavily("q") == []
    assert tv.get_last_tavily_error().startswith("TimeoutError")
