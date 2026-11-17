"""Offline regression for the web-research evidence helper boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.application import web_lookup_service
from src.application.web_lookup_evidence import (
    ResearchReadBudget,
    _bounded_inherited_notes,
    _bounded_read_result,
    _canonical_source_url,
    _format_research_source_block,
    _safe_inherited_source,
)


def test_source_normalization_and_legacy_service_import_still_agree():
    tracked = "HTTPS://EXAMPLE.COM/read/?utm_source=email&id=4#section"
    assert _canonical_source_url(tracked) == "https://example.com/read?id=4"
    assert web_lookup_service._canonical_source_url is _canonical_source_url
    assert web_lookup_service.ResearchReadBudget is ResearchReadBudget


def test_inherited_notes_only_include_previously_read_sources():
    run = SimpleNamespace(
        selected_sources=[
            {"item": {"url": "https://example.com/a?utm_medium=mail"},
             "read": {"status": "read"}},
            {"item": {"url": "https://example.com/b"},
             "read": {"status": "failed"}},
        ],
        research_context={"deep": {"notes": [
            {"url": "https://example.com/a", "facts": "supported"},
            {"url": "https://example.com/b", "facts": "not validated"},
        ]}},
    )
    assert [row["facts"] for row in _bounded_inherited_notes(run)] == ["supported"]
    assert _safe_inherited_source({"item": {"url": "https://example.com/a",
                                             "secret": "must not pass"}}) == {
        "item": {"url": "https://example.com/a"},
        "assessment": {},
        "evidence_state": "inherited_candidate",
    }


def test_candidate_without_readable_content_never_enters_synthesis():
    candidate = {"item": {"title": "UNREAD CLAIM", "url": "https://example.com"},
                 "read": {"ok": False, "content": "misleading candidate summary"}}
    assert _format_research_source_block("question", [], [candidate]) == ""
    candidate["read"] = {"ok": True, "content": "verified full page"}
    body = _format_research_source_block("question", [], [candidate])
    assert "verified full page" in body


def test_bounded_read_and_environment_budget_are_still_strict():
    result, used = _bounded_read_result(
        {"content": "abcdef", "readme": "1234", "entries": [{"path": "p"}] * 201},
        max_chars=3,
    )
    assert (result["content"], result["readme"], used) == ("abc", "123", 6)
    assert result["content_truncated"] and result["readme_truncated"]
    assert len(result["entries"]) == 200
    with patch.dict("os.environ", {
        "WEB_RESEARCH_MAX_READS": "999",
        "WEB_RESEARCH_MAX_CHARS_PER_SOURCE": "1",
        "WEB_RESEARCH_MAX_TOTAL_CHARS": "invalid",
    }):
        budget = ResearchReadBudget.from_env()
    assert (budget.max_reads, budget.max_chars_per_source, budget.max_total_chars) == (
        8, 500, 16000,
    )
