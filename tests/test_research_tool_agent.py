"""B-Search-2 controlled tool agent: action parsing, safety, quotas, loop."""

from __future__ import annotations

import json

import pytest

from src.web.research_tool_agent import AgentBudget, parse_action, parse_feed, run_tool_agent


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


def test_parse_feed_rss_and_atom():
    rss = "<rss><channel><item><title>A</title><link>https://ex.org/a</link></item></channel></rss>"
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>B</title><link href="https://ex.org/b"/></entry></feed>'
    assert parse_feed(rss) == [{"title": "A", "url": "https://ex.org/a"}]
    assert parse_feed(atom) == [{"title": "B", "url": "https://ex.org/b"}]


def test_feed_requires_confirmed_url():
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "feed", "url": "https://ex.org/feed.xml"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=gw, completion=completion, question="q", budget=AgentBudget())
    assert trace["calls"][0]["result"]["status"] == "pending_url_confirmation"


def test_safe_fetch_rejects_private_dns_without_requesting(monkeypatch):
    import src.web.research_tool_agent as agent

    requested: list[str] = []

    def fail(_host):
        raise ValueError("unsafe_target")

    monkeypatch.setattr(agent, "_resolve_public_ips", fail)
    monkeypatch.setattr(agent, "_http_get_pinned", lambda *a, **k: requested.append("x"))
    with pytest.raises(ValueError):
        agent.safe_fetch("https://example.org/feed", timeout=1)
    assert requested == []


def test_safe_fetch_never_contacts_private_redirect_target(monkeypatch):
    import src.web.research_tool_agent as agent

    opened: list[str] = []
    monkeypatch.setattr(agent, "_resolve_public_ips", lambda host: ["1.2.3.4"])

    def fake_get(url, host, ip, timeout):
        opened.append(url)
        return (302, {"location": "http://127.0.0.1/x"}, "")

    monkeypatch.setattr(agent, "_http_get_pinned", fake_get)
    with pytest.raises(ValueError):
        agent.safe_fetch("https://example.org/feed", timeout=1)
    assert opened == ["https://example.org/feed"]


def test_read_page_blocked_when_host_not_public(monkeypatch):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: False)
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "read_page", "url": "https://ex.org/known"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=gw, completion=completion, question="q", budget=AgentBudget(),
                           initial_urls=("https://ex.org/known",))
    assert trace["calls"][0]["result"]["status"] == "blocked_unsafe_target"
    assert gw.reads == []


def test_agent_records_invalid_action_and_continues():
    gw = FakeGateway()
    completion = make_completion([
        {"tool": "nonsense"},
        {"tool": "finish", "reason": "after bad action"},
    ])
    trace = run_tool_agent(gateway=gw, completion=completion, question="q", budget=AgentBudget())
    assert trace["calls"][0]["error"]
    assert trace["stop_reason"] == "finished"


def _feed_run(monkeypatch, fetch):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "safe_fetch", fetch)
    completion = make_completion([{"tool": "feed", "url": "https://ex.org/f.xml"}, {"tool": "finish"}])
    return run_tool_agent(gateway=FakeGateway(), completion=completion, question="q",
                          budget=AgentBudget(), initial_urls=("https://ex.org/f.xml",))


def test_feed_empty_vs_unavailable(monkeypatch):
    empty = _feed_run(monkeypatch, lambda url, timeout=15.0, deadline=None: "<rss><channel></channel></rss>")
    assert empty["calls"][0]["feed_status"] == "empty"

    invalid = _feed_run(monkeypatch, lambda url, timeout=15.0, deadline=None: "<rss><channel>")
    assert invalid["calls"][0]["feed_status"] == "unavailable"

    def unreachable(url, timeout=15.0, deadline=None):
        raise ValueError("dns_failed")

    down = _feed_run(monkeypatch, unreachable)
    assert down["calls"][0]["feed_status"] == "unavailable"


def test_source_chain_records_registry_feed_entry_and_basis(monkeypatch):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    monkeypatch.setattr(
        agent, "safe_fetch",
        lambda url, timeout=15.0, deadline=None:
        "<rss><channel><item><title>t</title><link>https://ex.org/a</link></item></channel></rss>",
    )
    completion = make_completion([
        {"tool": "feed", "url": "https://ex.org/f.xml"},
        {"tool": "read_page", "url": "https://ex.org/a"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion, question="q",
                           budget=AgentBudget(), registry_sources=(("src-1", "https://ex.org/f.xml"),))
    chain = trace["source_chain"]
    assert chain and chain[0]["entry_url"] == "https://ex.org/a"
    assert chain[0]["feed_url"] == "https://ex.org/f.xml"
    assert chain[0]["basis"] == "feed_entry"
