from __future__ import annotations

import json

from src.news.audit import save_news_audit


def test_save_news_audit_writes_json_and_markdown(tmp_path, monkeypatch):
    from src.news import audit

    monkeypatch.setattr(
        audit,
        "feed_health_rows",
        lambda: [
            {
                "source": "Google News",
                "status": "ok",
                "item_count": 3,
                "url": "https://news.example/rss",
            }
        ],
    )

    artifact = save_news_audit(
        query_text="python url parsing",
        news_items=[
            {
                "title": "Docs",
                "source": "Docs",
                "link": "https://docs.python.org/3/",
                "resolved_link": "https://docs.python.org/3/",
                "resolution_status": "original",
                "article_excerpt": "body",
                "article_status": "正文已读｜本地 HTMLParser",
            }
        ],
        source_block="【联网检索】\n查询：python url parsing",
        digest="digest",
        article_coverage={"total": 1, "with_text": 1},
        warnings=[],
        feed_warnings=[],
        elapsed_ms=123,
        audit_dir=tmp_path,
        now=1_800_000_000.0,
    )

    assert artifact.run_id.endswith("-python-url-parsing")
    markdown = (tmp_path / f"{artifact.run_id}.md").read_text(encoding="utf-8")
    payload = json.loads((tmp_path / f"{artifact.run_id}.json").read_text(encoding="utf-8"))

    assert "# News Audit" in markdown
    assert "## Pipeline Trace" in markdown
    assert "## Feed Health" in markdown
    assert payload["pipeline_trace"]["article_text_items"] == 1
    assert payload["feed_health"][0]["source"] == "Google News"
