"""Slice-1 acceptance: confirmed-unread candidates are surfaced and reused, the URL
gate still rejects guesses, the candidate pipeline is traceable with split states,
budgets are unchanged, and an ineligible candidate is never recommended."""
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


def _read_rows(trace):
    return [row for row in trace["candidate_trace"] if row["tool"] == "read_page"]


def _prompt_candidates(seen):
    return {row["url"] for ctx in seen for row in (ctx.get("confirmed_unread") or [])}


def test_guessed_url_is_rejected_and_confirmed_candidate_is_used():
    seen: list[dict] = []
    completion = _completion([
        {"tool": "search", "query": "q"},
        {"tool": "read_page", "url": "https://docs.python.org/3/whatsnew/3.13.html"},
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ], seen)
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion, question="q",
                           budget=AgentBudget())

    rows = _read_rows(trace)
    assert rows[0]["confirmed"] is False and rows[0]["attempted"] is False
    assert rows[0]["failure_reason"] == "url_not_from_search_result"
    assert rows[1]["confirmed"] is True and rows[1]["succeeded"] is True
    assert "https://example.org/a" in _prompt_candidates(seen)


def test_deep_page_discovered_via_follow_is_read_through(monkeypatch):
    """End-to-end: follow a directory -> a NEW deep page becomes a legal candidate ->
    it is shown -> the model reads it -> the read succeeds with basis followed_link."""
    monkeypatch.setattr(
        "src.web.safe_http.safe_fetch_result",
        lambda url, timeout=8.0, max_bytes=300_000, deadline=None: {
            "text": '<html><body><a href="/wiki/target">target article</a></body></html>',
            "final_url": url, "content_type": "text/html", "content_encoding": "",
        },
    )
    seen: list[dict] = []
    completion = _completion([
        {"tool": "follow", "url": "https://example.org/dir"},
        {"tool": "read_page", "url": "https://example.org/wiki/target"},
        {"tool": "finish"},
    ], seen)
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion,
                           question="target", budget=AgentBudget(),
                           initial_urls=("https://example.org/dir",))

    follow_row = [r for r in trace["candidate_trace"] if r["tool"] == "follow"][0]
    assert "https://example.org/wiki/target" in follow_row["newly_confirmed"]
    assert "https://example.org/wiki/target" in _prompt_candidates(seen)

    deep = [r for r in _read_rows(trace) if r["url"] == "https://example.org/wiki/target"]
    assert deep and deep[0]["confirmed"] is True and deep[0]["attempted"] is True
    assert deep[0]["succeeded"] is True and deep[0]["basis"] == "followed_link"
    assert any(b["ok"] and b["url"] == "https://example.org/wiki/target" for b in trace["bodies"])


def test_repeated_follow_reports_no_newly_confirmed(monkeypatch):
    monkeypatch.setattr(
        "src.web.safe_http.safe_fetch_result",
        lambda url, timeout=8.0, max_bytes=300_000, deadline=None: {
            "text": '<html><body><a href="/wiki/target">t</a></body></html>',
            "final_url": url, "content_type": "text/html", "content_encoding": "",
        },
    )
    completion = _completion([
        {"tool": "follow", "url": "https://example.org/dir-one"},
        {"tool": "follow", "url": "https://example.org/dir-two"},
        {"tool": "finish"},
    ], [])
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion,
                           question="target", budget=AgentBudget(),
                           initial_urls=("https://example.org/dir-one",
                                         "https://example.org/dir-two"))
    follows = [r for r in trace["candidate_trace"] if r["tool"] == "follow"]
    assert len(follows) == 2, follows
    assert follows[0]["newly_confirmed"], follows
    assert follows[1]["newly_confirmed"] == []  # already known -> not "new" again


def test_excluded_candidate_is_not_recommended(monkeypatch):
    """`confirmed` does not imply `eligible`: an excluded source must not be offered."""
    refused = "https://example.org/blocked"
    import src.web.research.entry_selection as selection

    def admission(title, snippet, question):
        return {"decision": "refuse", "reason": "off_topic"}

    monkeypatch.setattr(selection, "search_admission", admission)
    gateway = FakeGateway(results=[{"title": "t", "url": refused, "snippet": "s"}])
    seen: list[dict] = []
    completion = _completion([
        {"tool": "search", "query": "q"},
        {"tool": "read_page", "url": refused},
        {"tool": "finish"},
    ], seen)
    trace = run_tool_agent(gateway=gateway, completion=completion, question="q",
                           budget=AgentBudget())

    assert refused not in _prompt_candidates(seen)  # never recommended
    row = _read_rows(trace)[0]
    assert row["eligible"] is False and row["attempted"] is False
    assert row["failure_reason"].startswith("entry_not_eligible")
    assert trace["calls"][1]["result"]["status"] == "entry_not_eligible"  # gate unchanged


def test_budgets_are_unchanged_by_slice1():
    default = AgentBudget()
    assert (default.max_rounds, default.max_searches, default.max_reads) == (6, 4, 3)
    assert default.hard_seconds == 60.0
    assert (BSEARCH_SHADOW_MAX_ROUNDS, BSEARCH_SHADOW_MAX_SEARCHES,
            BSEARCH_SHADOW_MAX_READS) == (6, 4, 3)
    assert BSEARCH_SHADOW_BUDGET_SECONDS == 20.0
