"""Read-backed excerpts arrive before synthesis without acquiring answer authority."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.api.routes.chat_routes import _research_progress
from src.web.research.research_interaction import interaction_event


def research_run():
    return SimpleNamespace(
        id="run-live", status="running", stage="reading", version=2,
        provider_status="", stop_reason="", error="", query_attempts=[{}],
        research_context={
            "research_mode": "deep", "read_summary": {"successful": 1},
            "deep": {"notes": [{"url": "https://example.org/source", "title": "Source title", "facts": "Actual page body."}]},
        },
        selected_sources=[{
            "item": {"url": "https://example.org/source", "snippet": "Search snippet must not appear"},
            "assessment": {"url": "https://example.org/source", "worth_reading": True},
            "read": {"url": "https://example.org/source", "status": "read", "ok": True, "content": "Actual page body."},
        }],
    )


def test_read_excerpt_arrives_while_running_and_does_not_change_authority():
    run = research_run()
    before = deepcopy(vars(run))
    progress = _research_progress(run)
    assert progress["status"] == "running"
    assert progress["read_count"] == 1
    assert progress["findings"][0]["text"] == "Actual page body."
    assert progress["findings"][0]["kind"] == "source_excerpt"
    assert progress["findings"] == _research_progress(run)["findings"]
    assert "Search snippet" not in str(progress)
    assert "source_block" not in progress
    assert vars(run) == before


@pytest.mark.parametrize("invalid", [
    "no-read", "failed", "ineligible", "not-worth-reading", "invented-note",
    "private", "javascript", "malformed-url", "superseded", "removed-note", "wrong-request",
])
def test_candidate_failed_or_invalidated_material_is_never_an_early_finding(invalid):
    run = research_run()
    record = run.selected_sources[0]
    note = run.research_context["deep"]["notes"][0]
    if invalid == "no-read":
        record.pop("read")
    elif invalid == "failed":
        record["read"]["ok"] = False
    elif invalid == "ineligible":
        record["read"]["answer_eligible"] = False
    elif invalid == "not-worth-reading":
        record["assessment"]["worth_reading"] = False
    elif invalid == "invented-note":
        note["facts"] = "Invented finding absent from the page"
    elif invalid in {"private", "javascript", "malformed-url"}:
        record["read"]["url"] = {"private": "http://127.0.0.1/secret", "javascript": "javascript:alert(1)", "malformed-url": "https://[bad"}[invalid]
    elif invalid == "superseded":
        note["superseded"] = True
    elif invalid == "removed-note":
        run.research_context["deep"]["notes"] = []
    elif invalid == "wrong-request":
        record["read"]["requested_url"] = "https://example.org/other"
    assert interaction_event(run)["findings"] == []


def test_excerpt_count_size_deduplication_and_terminal_retention():
    run = research_run()
    run.selected_sources = []
    notes = []
    for number in range(6):
        url = f"https://example.org/{number}"
        text = str(number) * 600
        notes.append({"url": url, "title": "title" * 100, "facts": text})
        run.selected_sources.append({
            "item": {"url": url}, "assessment": {"url": url, "worth_reading": True},
            "read": {"status": "read", "ok": True, "content": text},
        })
    notes.append(dict(notes[-1]))
    run.research_context["deep"]["notes"] = notes
    findings = interaction_event(run)["findings"]
    assert len(findings) == 3
    assert len({finding["url"] for finding in findings}) == 3
    assert all(len(finding["text"]) <= 280 and len(finding["title"]) <= 160 for finding in findings)
    run.status = "cancelled"
    assert interaction_event(run)["findings"] == findings


def test_active_metrics_remain_authoritative_for_active_read_count():
    run = research_run()
    run.research_context["claim_engine_metrics"] = {"read_count": 7}
    assert _research_progress(run)["read_count"] == 7
