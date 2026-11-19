from __future__ import annotations

from src.news.pipeline import (
    build_item_trace,
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


def test_build_item_trace_uses_search_snippet_before_title_only():
    trace = build_item_trace(
        {
            "title": "Search result",
            "link": "https://example.com",
            "search_excerpt": "Provider supplied snippet",
        }
    )

    assert trace.evidence_level == "search_snippet"
