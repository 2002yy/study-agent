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


def test_json_ld_author_and_dates_are_reported_as_declared():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "Article", "author": [{"name": "Alice"}, {"name": "Bob"}],
     "datePublished": "2024-01-01", "dateModified": "2026-11-20"}
    </script>
    </head><body></body></html>
    """
    text = raw_content.page_metadata(html)

    assert "author=Alice, Bob" in text
    assert "published=2024-01-01" in text
    assert "modified=2026-11-20" in text
    assert "not independently verified" in text


def test_metadata_falls_back_to_meta_tags():
    html = """
    <html><head>
      <meta name="author" content="Carol">
      <meta property="article:published_time" content="2025-05-05T10:00:00Z">
    </head></html>
    """
    text = raw_content.page_metadata(html)

    assert "author=Carol" in text
    assert "published=2025-05-05" in text


def test_citation_links_separate_body_from_navigation():
    html = """
    <html><body>
      <nav><a href="https://site.example/section">Section</a></nav>
      <article>
        <p>As reported in the <a href="https://doi.org/10.1/x">original paper</a>.</p>
        <p>See <a href="https://site.example/other">another page</a>.</p>
      </article>
      <footer><a href="https://twitter.com/site">Follow us</a></footer>
    </body></html>
    """
    text = raw_content.citation_links(html, "https://site.example/post")

    assert "[body,cite-hint] original paper" in text
    assert "[body,same-site] another page" in text
    assert "[nav,same-site] Section" in text
    assert "[nav] Follow us" in text


def test_citation_links_are_bounded_and_deduplicated():
    links = "".join(
        f'<p><a href="https://x.example/{i}">item {i}</a></p>' for i in range(40)
    )
    html = f"<html><body>{links}</body></html>"
    text = raw_content.citation_links(html, "https://site.example/post", limit=10)

    assert text.count("— https://x.example/") == 10
    assert "40 body links" in text


def test_rss_feed_becomes_an_entry_list():
    payload = """<?xml version="1.0"?>
    <rss><channel><title>Blog</title>
      <item><title>First</title><link>https://blog.example/1</link>
        <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
        <description>&lt;p&gt;hello&lt;/p&gt;</description></item>
    </channel></rss>
    """
    text = raw_content.feed_summary(payload)

    assert "[feed] 1 entries" in text
    assert "First" in text
    assert "https://blog.example/1" in text
    assert "hello" in text


def test_atom_feed_becomes_an_entry_list():
    payload = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Atom post</title>
        <link rel="alternate" href="https://blog.example/atom"/>
        <updated>2026-01-01T00:00:00Z</updated>
        <summary>atom summary</summary></entry>
    </feed>
    """
    text = raw_content.feed_summary(payload)

    assert "Atom post" in text
    assert "https://blog.example/atom" in text
    assert "atom summary" in text


def test_fetch_adds_metadata_and_links(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    html = """
    <html><head>
      <script type="application/ld+json">
      {"author": {"name": "Alice"}, "datePublished": "2024-01-01"}
      </script>
    </head><body>
      <p>body <a href="https://doi.org/10.1/x">source paper</a></p>
    </body></html>
    """
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: (html, url, "text/html", ""),
    )
    monkeypatch.setattr(
        article_fetcher,
        "read_html_locally",
        lambda html, url="", max_chars=5000: ReaderResult(text="body", method="local_x"),
    )
    result = article_fetcher.fetch_article_read_result(
        "https://example.com/post", max_chars=4000
    )

    assert "[metadata] author=Alice" in result.text
    assert "[links]" in result.text
    assert "source paper" in result.text


def test_feed_payload_uses_feed_text_method(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    payload = """<?xml version="1.0"?>
    <rss><channel><item><title>First</title><link>https://x.example/1</link></item></channel></rss>
    """
    monkeypatch.setattr(article_fetcher, "_is_fetchable_article_url", lambda _url: True)
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("", url, "application/rss+xml", "non_html_resource"),
    )
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_text_payload",
        lambda url, timeout, max_bytes: (payload, url, "application/rss+xml", ""),
    )
    result = article_fetcher.fetch_article_read_result(
        "https://blog.example/feed.xml", max_chars=4000
    )

    assert result.ok is True
    assert result.method == "feed_text"
    assert "First" in result.text


def test_pdf_payload_is_extracted_as_text(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("", url, "application/pdf", "non_html_resource"),
    )
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_binary_payload",
        lambda url, timeout, max_bytes: (b"%PDF-1.4", url, "application/pdf", ""),
    )
    monkeypatch.setattr(
        raw_content, "pdf_text", lambda data, max_chars=20_000: "[pdf] 2 pages\n[page 1]\nbody"
    )
    result = article_fetcher.fetch_article_read_result(
        "https://example.com/paper.pdf", max_chars=4000
    )

    assert result.ok is True
    assert result.method == "pdf_text"
    assert "[page 1]" in result.text


def test_unreadable_pdf_fails_closed(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: ("", url, "application/pdf", "non_html_resource"),
    )
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_binary_payload",
        lambda url, timeout, max_bytes: (b"not a pdf", url, "application/pdf", ""),
    )
    monkeypatch.setattr(raw_content, "pdf_text", lambda data, max_chars=20_000: "")
    result = article_fetcher.fetch_article_read_result(
        "https://example.com/broken.pdf", max_chars=4000
    )

    assert result.ok is False
    assert result.reason == "pdf_unreadable"


def test_page_toc_lists_headings_with_anchors():
    html = """
    <html><body>
      <h1 id="top">Guide</h1>
      <h2 id="install">Install</h2>
      <h3>Options</h3>
      <h2 id="deploy">Deploy</h2>
    </body></html>
    """
    text = raw_content.page_toc(html, "https://docs.example/guide")

    assert "[toc]" in text
    assert "H2 Install — https://docs.example/guide#install" in text
    assert "H3 Options" in text
    assert "H2 Deploy" in text


def test_section_text_reads_only_the_anchor():
    html = """
    <html><body>
      <h2 id="install">Install</h2>
      <p>install steps</p>
      <h2 id="deploy">Deploy</h2>
      <p>deploy steps</p>
    </body></html>
    """
    text = raw_content.section_text(html, "install")

    assert "[section #install]" in text
    assert "install steps" in text
    assert "deploy steps" not in text


def test_fragment_url_reads_one_section(monkeypatch):
    article_fetcher._ARTICLE_CACHE.clear()
    html = """
    <html><body>
      <h2 id="install">Install</h2><p>install steps</p>
      <h2 id="deploy">Deploy</h2><p>deploy steps</p>
    </body></html>
    """
    monkeypatch.setattr(
        article_fetcher,
        "_fetch_html_payload",
        lambda url, timeout, max_bytes: (html, url, "text/html", ""),
    )
    result = article_fetcher.fetch_article_read_result(
        "https://example.com/guide#install", max_chars=4000
    )

    assert result.ok is True
    assert result.method == "section_text"
    assert "install steps" in result.text
    assert "deploy steps" not in result.text


def test_srt_and_vtt_keep_timestamps():
    srt = """1
00:00:01,000 --> 00:00:03,000
Hello there

2
00:00:04,500 --> 00:00:06,000
General Kenobi
"""
    vtt = """WEBVTT

00:00:01.000 --> 00:00:02.000
<c>first line</c>

00:00:02.000 --> 00:00:03.000
second line
"""
    srt_text = raw_content.subtitle_text(srt, "srt")
    vtt_text = raw_content.subtitle_text(vtt, "vtt")

    assert "[subtitles] 2 cues" in srt_text
    assert "[00:00:01] Hello there" in srt_text
    assert "[00:00:04] General Kenobi" in srt_text
    assert "[00:00:01] first line" in vtt_text
    assert "[00:00:02] second line" in vtt_text


def test_ass_dialogue_lines_are_parsed():
    ass = """[Script Info]
Title: demo

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:05.00,0:00:07.00,Default,,0,0,0,,{\\i1}styled line{\\i0}
"""
    text = raw_content.subtitle_text(ass, "ass")

    assert "[00:00:05] styled line" in text


def test_podcast_feed_keeps_audio_and_transcript_links():
    payload = """<?xml version="1.0"?>
    <rss xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel>
      <item><title>Episode 1</title><link>https://pod.example/1</link>
        <enclosure url="https://cdn.example/1.mp3" type="audio/mpeg" length="1"/>
        <podcast:transcript url="https://pod.example/1.vtt" type="text/vtt"/>
        <description>episode notes</description>
      </item>
    </channel></rss>
    """
    text = raw_content.feed_summary(payload)

    assert "audio=https://cdn.example/1.mp3 (not transcribed)" in text
    assert "transcript=https://pod.example/1.vtt" in text
