from __future__ import annotations

from src.news.pipeline import (
    build_item_trace,
    build_pipeline_trace,
    format_feed_health_markdown,
    format_pipeline_trace_markdown,
)


def test_build_item_trace_marks_article_text_and_redirect_hops():
    trace = build_item_trace(
        {
            "title": "Docs",
            "source": "Google News",
            "link": "https://news.example/redirect?url=https%3A%2F%2Fdocs.python.org%2F3%2F",
            "resolved_link": "https://docs.python.org/3/",
            "canonical_url": "https://docs.python.org/3/",
            "domain": "docs.python.org",
            "resolution_status": "resolved",
            "article_status": "正文已读｜本地 trafilatura",
            "redirect_hops": [
                {"source": "input", "status": "received", "is_safe": True},
                {"source": "query_parameter", "status": "extracted", "is_safe": True},
            ],
            "domain_policy": {
                "blocked": False,
                "reasons": ["prefer-tech-domain"],
            },
        }
    )

    assert trace.evidence_level == "article_text"
    assert trace.redirect_hop_count == 2
    assert trace.domain_policy_reasons == ("prefer-tech-domain",)


def test_build_pipeline_trace_summarizes_round_health():
    trace = build_pipeline_trace(
        "python url parsing",
        [
            {
                "title": "Article text",
                "source": "Docs",
                "link": "https://docs.python.org/3/",
                "resolved_link": "https://docs.python.org/3/",
                "resolution_status": "original",
                "article_excerpt": "Useful body",
                "article_status": "正文已读｜本地 HTMLParser",
            },
            {
                "title": "Blocked login",
                "source": "Bad Source",
                "link": "https://accounts.example.com/login",
                "resolved_link": "https://accounts.example.com/login",
                "resolution_status": "original",
                "article_status": "域名策略过滤，未读取正文",
                "domain_policy": {"blocked": True, "reasons": ["login-path"]},
            },
            {
                "title": "Unsafe redirect",
                "source": "Wrapped",
                "link": "https://news.example/redirect",
                "resolved_link": "http://127.0.0.1/admin",
                "resolution_status": "unsafe",
                "redirect_hops": [
                    {"source": "query_parameter", "status": "blocked", "is_safe": False}
                ],
            },
        ],
        feed_warnings=[
            {"source": "Google News", "error_type": "ValueError", "message": "bad xml"}
        ],
    )

    assert trace.total_items == 3
    assert trace.article_text_items == 1
    assert trace.blocked_items == 1
    assert trace.title_only_items == 1
    assert trace.unsafe_redirect_items == 1
    assert trace.resolution_counts == {"original": 2, "unsafe": 1}
    assert trace.feed_warnings[0]["source"] == "Google News"
    assert trace.to_dict()["items"][0]["title"] == "Article text"


def test_format_pipeline_trace_markdown_includes_audit_fields():
    trace = build_pipeline_trace(
        "python url parsing",
        [
            {
                "title": "Unsafe redirect",
                "source": "Wrapped",
                "link": "https://news.example/redirect",
                "resolved_link": "http://127.0.0.1/admin",
                "domain": "127.0.0.1",
                "resolution_status": "unsafe",
                "redirect_hops": [
                    {"source": "query_parameter", "status": "blocked", "is_safe": False}
                ],
                "domain_policy": {"blocked": False, "reasons": ["missing-domain"]},
            }
        ],
    )

    report = format_pipeline_trace_markdown(trace)

    assert "# News Pipeline Trace" in report
    assert "- unsafe_redirect_items: 1" in report
    assert "unsafe_redirect: blocked" in report
    assert "domain_policy: missing-domain" in report


def test_format_feed_health_markdown_renders_errors():
    report = format_feed_health_markdown(
        [
            {
                "source": "Google News",
                "status": "error",
                "item_count": 0,
                "error_type": "ValueError",
                "message": "bad xml",
            }
        ]
    )

    assert "# Feed Health" in report
    assert "Google News: error (0 items)" in report
    assert "ValueError bad xml" in report
