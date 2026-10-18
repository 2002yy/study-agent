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


def test_comparison_reserves_space_for_each_question_and_reports_real_body_gaps():
    run = research_run()
    run.selected_sources = []
    deep = run.research_context["deep"]
    deep["plan"] = [{"sub_question": question, "status": "done"} for question in ["Photoshop scripting", "GIMP scripting", "PSD compatibility"]]
    deep["notes"] = []
    for index, question in enumerate(["GIMP scripting"] + ["Photoshop scripting"] * 5):
        url = f"https://example.org/{index}"
        text = f"Read body {index}"
        deep["notes"].append({"url": url, "title": str(index), "facts": text, "sub_question": question})
        run.selected_sources.append({
            "item": {"url": url}, "assessment": {"url": url, "worth_reading": True},
            "read": {"ok": True, "status": "read", "content": text},
        })
    before = deepcopy(vars(run))
    event = interaction_event(run)
    assert len(event["findings"]) == 3
    assert {item["question"] for item in event["findings"]} == {"Photoshop scripting", "GIMP scripting"}
    assert event["reading_gaps"] == ["PSD compatibility"]
    # Execution's done flag cannot manufacture a source for the third question.
    assert vars(run) == before


def test_same_page_can_supply_two_questions_without_colliding_excerpt_identity():
    run = research_run()
    deep = run.research_context["deep"]
    first = deep["notes"][0]
    first["sub_question"] = "first dimension"
    deep["notes"].append({**first, "sub_question": "second dimension"})
    deep["plan"] = [{"sub_question": question, "status": "done"} for question in ["first dimension", "second dimension"]]
    event = interaction_event(run)
    assert len(event["findings"]) == 2
    assert len({item["id"] for item in event["findings"]}) == 2
    assert event["reading_gaps"] == []


def test_corrected_and_cancelled_questions_do_not_reappear_as_sources_or_gaps():
    run = research_run()
    deep = run.research_context["deep"]
    deep["notes"][0]["sub_question"] = "RTX 4060 measurements"
    deep["corrections"] = [{"old": "4060", "new": "5060"}]
    deep["plan"] = [
        {"sub_question": "RTX 4060 measurements", "status": "done"},
        {"sub_question": "RTX 5060 measurements", "status": "pending"},
        {"sub_question": "cancelled task", "status": "cancelled"},
    ]
    event = interaction_event(run)
    assert event["findings"] == []
    assert event["reading_gaps"] == ["RTX 5060 measurements"]
    deep["plan"] = []
    assert interaction_event(run)["reading_gaps"] == []


def test_display_cap_does_not_turn_hidden_read_material_into_a_false_gap():
    run = research_run()
    deep = run.research_context["deep"]
    note = dict(deep["notes"][0])
    deep["plan"] = [{"sub_question": f"question {index}", "status": "done"} for index in range(4)]
    deep["notes"] = [{**note, "sub_question": task["sub_question"]} for task in deep["plan"]]
    event = interaction_event(run)
    assert len(event["findings"]) == 3
    assert event["reading_gaps"] == []
