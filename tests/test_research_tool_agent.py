"""B-Search-2 controlled tool agent: action parsing, safety, quotas, loop."""

from __future__ import annotations

import json

import pytest

from src.web.research_tool_agent import AgentBudget, parse_action, run_tool_agent


class FakeGateway:
    def __init__(self, results=None, body_ok=True):
        self.searches = []
        self.reads = []
        self._results = results or [{"title": "t", "url": "https://example.org/a", "snippet": "s"}]
        self._body_ok = body_ok

    def search_exact(self, query, *, max_results=5):
        self.searches.append(query)
        return {"status": "ok", "reason": "results_found", "results": self._results}

    def read(self, url, *, max_chars=6000, timeout=8):
        self.reads.append(url)
        if not self._body_ok:
            return {"ok": False, "url": url, "error": "HTTPError: 404"}
        return {"ok": True, "url": url, "content": "relevant body text about the topic"}


def make_completion(actions):
    seq = list(actions)

    def completion(**kwargs):
        return json.dumps(seq.pop(0))

    return completion


def test_parse_action_validates():
    assert parse_action('{"tool":"search","query":"q","reason":"r"}')["tool"] == "search"
    assert parse_action({"tool": "read_page", "url": "https://example.org/a"})["url"] == "https://example.org/a"
    assert parse_action({"tool": "finish"})["tool"] == "finish"
    with pytest.raises(ValueError):
        parse_action({"tool": "search", "query": ""})
    with pytest.raises(ValueError):
        parse_action({"tool": "read_page", "url": "file:///etc/passwd"})
    with pytest.raises(ValueError):
        parse_action({"tool": "exec", "cmd": "rm -rf"})


def test_agent_loops_search_then_read_then_finish():
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "search", "query": "topic keywords", "reason": "find"},
        {"tool": "read_page", "url": "https://example.org/a", "reason": "read the article"},
        {"tool": "finish", "reason": "done"},
    ])
    trace = run_tool_agent(gateway=gw, completion=completion, question="q", budget=AgentBudget())
    assert trace["searches"] == 1 and trace["reads"] == 1
    assert trace["stop_reason"] == "finished"
    assert trace["bodies"][0]["ok"] is True
    assert trace["bodies"][0]["chars"] > 0
    assert trace["publication_authority"] is False


def test_agent_enforces_quotas_and_reports_failure():
    gw = FakeGateway(body_ok=False)
    completion = make_completion([
        {"tool": "search", "query": "a"}, {"tool": "search", "query": "b"},
        {"tool": "search", "query": "c"}, {"tool": "search", "query": "d"},
        {"tool": "search", "query": "e"},  # exceeds search quota
        {"tool": "read_page", "url": "https://example.org/x"},  # 404 body
        {"tool": "finish"},
    ])
    trace = run_tool_agent(
        gateway=gw, completion=completion, question="q",
        budget=AgentBudget(max_rounds=7, max_searches=4, max_reads=2),
        initial_urls=("https://example.org/x",),
    )
    assert trace["searches"] == 4
    assert any(c.get("result", {}).get("reason") == "search_quota" for c in trace["calls"])
    assert trace["bodies"][0]["ok"] is False


def test_read_requires_confirmed_url():
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "read_page", "url": "https://example.org/guessed"},  # not from any search
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=gw, completion=completion, question="q", budget=AgentBudget())
    assert trace["calls"][0]["result"]["status"] == "pending_url_confirmation"
    assert gw.reads == [] and trace["reads"] == 0


def test_initial_urls_are_readable_without_search():
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "read_page", "url": "https://example.org/known"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(
        gateway=gw, completion=completion, question="q", budget=AgentBudget(),
        initial_urls=("https://example.org/known",),
    )
    assert trace["reads"] == 1 and trace["bodies"][0]["ok"] is True


def test_agent_records_invalid_action_and_continues():
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "nonsense"},
        {"tool": "finish", "reason": "after bad action"},
    ])
    trace = run_tool_agent(gateway=gw, completion=completion, question="q", budget=AgentBudget())
    assert trace["calls"][0]["error"]
    assert trace["stop_reason"] == "finished"
