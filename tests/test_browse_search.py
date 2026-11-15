from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
