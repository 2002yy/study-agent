"""Tests for SearXNG URL building (B-Search-2B9-D): language + engine selection."""
from __future__ import annotations

from src.news.search_sources.searxng_source import build_searxng_search_url


def test_language_omitted_when_auto(monkeypatch):
    monkeypatch.delenv("SEARXNG_LANGUAGE", raising=False)
    monkeypatch.delenv("SEARXNG_ENGINES", raising=False)
    url = build_searxng_search_url("factorio interrupts", "https://s.example", categories="general")
    assert url and "language=" not in url          # forcing zh-CN zeroed google


def test_language_env_override(monkeypatch):
    monkeypatch.setenv("SEARXNG_LANGUAGE", "en")
    url = build_searxng_search_url("q", "https://s.example", categories="general")
    assert "language=en" in url


def test_engines_env_included(monkeypatch):
    monkeypatch.setenv("SEARXNG_ENGINES", "google")
    url = build_searxng_search_url("q", "https://s.example", categories="general")
    assert "engines=google" in url


def test_engines_absent_by_default(monkeypatch):
    monkeypatch.delenv("SEARXNG_ENGINES", raising=False)
    url = build_searxng_search_url("q", "https://s.example", categories="general")
    assert "engines=" not in url
