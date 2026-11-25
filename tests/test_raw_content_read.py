from __future__ import annotations

import json

from src.news import article_fetcher, raw_content
from src.news.readers.base import ReaderResult


def test_kind_uses_type_suffix_and_content():
    assert raw_content.kind_for("text/html; charset=utf-8", "https://x", "<html>") == "html"
    assert raw_content.kind_for("", "https://x/data.csv", "a,b") == "csv"
    assert raw_content.kind_for("text/plain", "https://x/notes.md", "# hi") == "markdown"
    assert raw_content.kind_for("application/json", "https://x/a.json", "{}") == "json"
    assert raw_content.kind_for("application/x-ndjson", "https://x/a", "{}") == "jsonl"
    assert raw_content.kind_for("text/plain", "https://x/a.jsonl", "{}") == "jsonl"
    assert raw_content.kind_for("text/plain", "https://x", "just words") == "text"
    assert raw_content.kind_for("text/plain", "https://x", "<!doctype html><p>x") == "html"


def test_csv_handles_quotes_and_ragged_rows():
    payload = 'model,memory,fps\n"RTX 4060",8GB,62\nRTX 5060,8GB\n'
    text = raw_content.csv_to_markdown(payload, max_chars=5000)

    assert "| model | memory | fps |" in text
    assert '| RTX 4060 | 8GB | 62 |' in text
    assert "| RTX 5060 | 8GB |  |" in text
    assert "ragged rows padded" in text


def test_tsv_uses_the_tab_delimiter():
    text = raw_content.csv_to_markdown("a\tb\n1\t2\n", delimiter="\t")
    assert "| a | b |" in text
    assert "| 1 | 2 |" in text


def test_large_json_returns_a_structure_summary_not_a_byte_cut():
    payload = json.dumps({"items": [{"id": i, "name": "x" * 50} for i in range(50)]})
    text = raw_content.json_summary(payload, max_chars=300)

    assert "structural summary" in text
    assert '"count": 50' in text
    assert not text.endswith("{")
    assert len(text) <= 301


def test_jsonl_counts_lines_and_reports_truncation():
    payload = "\n".join(json.dumps({"i": i}) for i in range(5))
    text = raw_content.jsonl_summary(payload, max_chars=200)

    assert "5 lines" in text
    assert "5 parsed" in text
    assert '{"i": 0}' in text


def test_markdown_is_kept_and_marked_when_truncated():
    payload = "# Title\n\n" + "word " * 100
    text = raw_content.clamp(payload, 60)

    assert text.startswith("# Title")
    assert "truncated" in text


def test_table_with_merged_cells_is_skipped_with_a_note():
    html = """
    <table>
      <tr><th colspan="2">GPU</th></tr>
      <tr><td>4060</td><td>62</td></tr>
    </table>
    """
    text = raw_content.tables_to_markdown(html)

    assert "merged cells" in text
    assert "| ---" not in text


def test_simple_table_becomes_markdown():
    html = """
    <table>
      <tr><th>型号</th><th>显存</th><th>均帧</th></tr>
      <tr><td>4060</td><td>8GB</td><td>62</td></tr>
      <tr><td>5060</td><td>8GB</td><td>81</td></tr>
    </table>
    """
    text = raw_content.tables_to_markdown(html)

    assert "| 型号 | 显存 | 均帧 |" in text
    assert "| 4060 | 8GB | 62 |" in text
    assert "| 5060 | 8GB | 81 |" in text


def test_fetch_dispatches_csv_to_table_text(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("a,b\n1,2\n", url, "text/csv", ""),
    )
    result = article_fetcher.fetch_article_read_result(
        "https://example.com/data.csv", max_chars=2000
    )

    assert result.ok is True
    assert result.method == "table_text"
    assert "| a | b |" in result.text


def test_fetch_keeps_tables_next_to_extracted_body(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    html = "<html><body><p>body text</p><table><tr><th>a</th></tr><tr><td>1</td></tr></table></body></html>"
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: (html, url, "text/html", ""),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url="", max_chars=5000: ReaderResult(text="body text", method="local_x"),
    )
    result = article_fetcher.fetch_article_read_result(
        "https://example.com/page", max_chars=4000
    )

    assert result.ok is True
    assert "body text" in result.text
    assert "[tables]" in result.text
    assert "| a |" in result.text
