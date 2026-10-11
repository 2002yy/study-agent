"""B-Search-2B7-A: OPML import (dedupe/merge) and deterministic Top-K recall."""

from __future__ import annotations

from tools.import_opml_directory import build_index
from src.web.research.source_directory import recall_sources


def _snapshot(tmp_path):
    feeds = tmp_path / "feeds"
    feeds.mkdir()
    # Same URL in the cn and en categories (with a raw '&') must merge, not duplicate.
    (feeds / "cn-tech.opml").write_text(
        '<opml><body><outline type="rss" text="Python猫" '
        'xmlUrl="https://a.example/feed?x=1&amp;y=2"/>'
        '<outline type="rss" text="Go 夜聊" xmlUrl="https://b.example/go"/></body></opml>',
        encoding="utf-8",
    )
    (feeds / "en-tech.opml").write_text(
        '<opml><body><outline type="rss" text="Other" '
        'xmlUrl="https://a.example/feed?x=1&y=2"/></body></opml>',
        encoding="utf-8",
    )
    (tmp_path / "stats.json").write_text('{"active_count": 2}', encoding="utf-8")
    return tmp_path


def test_import_dedupes_merges_and_defaults_cataloged(tmp_path):
    index = build_index(_snapshot(tmp_path))
    assert index["stats"]["final_sources"] == 2
    merged = [s for s in index["sources"] if s["xml_url"].startswith("https://a.example")]
    assert merged and merged[0]["categories"] == ["tech"]
    assert set(merged[0]["languages"]) == {"cn", "en"}
    assert all(s["status"] == "cataloged" for s in index["sources"])


def test_recall_matches_and_rejects_ambiguity(tmp_path):
    index = build_index(_snapshot(tmp_path))
    hit = recall_sources(index, "python 教程")
    assert hit and hit[0]["xml_url"].startswith("https://a.example")
    assert recall_sources(index, "围棋 提子 规则") == []      # CJK must not match "go"
    assert recall_sources(index, "今天晚饭吃什么") == []
