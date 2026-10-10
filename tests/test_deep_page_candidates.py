"""Slice-1 acceptance: confirmed-unread candidates are surfaced and reused, the URL
gate still rejects guesses, the candidate pipeline is traceable, and budgets are
unchanged."""
from __future__ import annotations

import json

import pytest

from src.application.research_shadow_seam import (
    BSEARCH_SHADOW_BUDGET_SECONDS,
    BSEARCH_SHADOW_MAX_READS,
    BSEARCH_SHADOW_MAX_ROUNDS,
    BSEARCH_SHADOW_MAX_SEARCHES,
)
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway


@pytest.fixture(autouse=True)
def _assume_public_hosts(monkeypatch):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)


def _completion(actions, seen):
    seq = list(actions)

    def run(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps(seq.pop(0))

    return run


def test_confirmed_unread_candidates_are_shown_and_reused():
    seen: list[dict] = []
    completion = _completion([
        {"tool": "search", "query": "q"},                                   # confirms example.org/a
        {"tool": "read_page", "url": "https://docs.python.org/3/whatsnew/3.13.html"},  # guessed
        {"tool": "read_page", "url": "https://example.org/a"},               # confirmed -> allowed
        {"tool": "finish"},
    ], seen)
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion, question="q",
                           budget=AgentBudget())

    # the guessed URL is still rejected (the gate is unchanged)
    reads = [c for c in trace["calls"] if c["action"].get("tool") == "read_page"]
    assert reads[0]["result"]["status"] == "pending_url_confirmation"
    assert reads[0]["result"]["reason"] == "url_not_from_search_result"
    # ... and the rejection now points at what the run already has
    rejection = [o for o in trace["calls"] if o.get("action", {}).get("tool") == "read_page"]
    assert rejection[0]["result"]["status"] == "pending_url_confirmation"
    # the confirmed candidate was read successfully
    assert any(b["ok"] and b["url"] == "https://example.org/a" for b in trace["bodies"])

    # the prompt shows the confirmed, not-yet-read URL so no search is wasted
    assert any(
        "https://example.org/a" in json.dumps(ctx.get("confirmed_unread", []), ensure_ascii=False)
        for ctx in seen
    ), seen


def test_candidate_pipeline_is_traceable(monkeypatch):
    # follow fetches through the shared transport (imported inline in that branch).
    monkeypatch.setattr(
        "src.web.safe_http.safe_fetch_result",
        lambda url, timeout=8.0, max_bytes=300_000, deadline=None: {
            "text": '<html><body><a href="/a">a</a></body></html>',
            "final_url": url, "content_type": "text/html", "content_encoding": "",
        },
    )
    completion = _completion([
        {"tool": "search", "query": "q"},
        {"tool": "follow", "url": "https://example.org/a"},
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ], [])
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion, question="q",
                           budget=AgentBudget())
    kinds = [row["tool"] for row in trace["candidate_trace"]]
    assert kinds == ["search", "follow", "read_page"]
    search_row = trace["candidate_trace"][0]
    assert search_row["results"] >= 1 and search_row["shown"]
    follow_row = trace["candidate_trace"][1]
    assert follow_row["raw_candidates"] >= 1
    assert "page_type" in follow_row and "shown" in follow_row
    read_row = trace["candidate_trace"][-1]
    assert read_row["admitted"] is True and read_row["basis"] == "search_result"


def test_budgets_are_unchanged_by_slice1():
    default = AgentBudget()
    assert (default.max_rounds, default.max_searches, default.max_reads) == (6, 4, 3)
    assert default.hard_seconds == 60.0
    assert (BSEARCH_SHADOW_MAX_ROUNDS, BSEARCH_SHADOW_MAX_SEARCHES,
            BSEARCH_SHADOW_MAX_READS) == (6, 4, 3)
    assert BSEARCH_SHADOW_BUDGET_SECONDS == 20.0
