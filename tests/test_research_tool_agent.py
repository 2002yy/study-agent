"""B-Search-2 controlled tool agent: action parsing, safety, quotas, loop."""

from __future__ import annotations

import json

import pytest

from src.web.research_tool_agent import AgentBudget, parse_action, parse_feed, run_tool_agent


@pytest.fixture(autouse=True)
def _assume_public_hosts(monkeypatch):
    # These tests exercise loop/quota/read logic, not DNS. In this environment real
    # hosts resolve to a fake-IP range and would otherwise be blocked as non-public.
    import src.web.research_tool_agent as _agent

    monkeypatch.setattr(_agent, "host_resolves_public", lambda host: True)


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
    import src.web.safe_http as sh

    requested: list[str] = []

    def fail(_host, **kwargs):
        raise ValueError("unsafe_target")

    monkeypatch.setattr(sh, "resolve_public_ips", fail)
    monkeypatch.setattr(sh, "http_get_pinned", lambda *a, **k: requested.append("x"))
    with pytest.raises(ValueError):
        sh.safe_fetch("https://example.org/feed", timeout=1)
    assert requested == []


def test_safe_fetch_never_contacts_private_redirect_target(monkeypatch):
    import src.web.safe_http as sh

    opened: list[str] = []
    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kwargs: ["1.2.3.4"])

    def fake_get(url, host, ip, *, timeout, max_bytes=300_000):
        opened.append(url)
        return (302, {"location": "http://127.0.0.1/x"}, "")

    monkeypatch.setattr(sh, "http_get_pinned", fake_get)
    with pytest.raises(ValueError):
        sh.safe_fetch("https://example.org/feed", timeout=1)
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
        "<rss><channel><item><title>python guide</title><link>https://ex.org/a</link></item></channel></rss>",
    )
    completion = make_completion([
        {"tool": "feed", "url": "https://ex.org/f.xml"},
        {"tool": "read_page", "url": "https://ex.org/a"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion, question="python guide",
                           budget=AgentBudget(), registry_sources=(("src-1", "https://ex.org/f.xml"),))
    chain = trace["source_chain"]
    assert chain and chain[0]["entry_url"] == "https://ex.org/a"
    assert chain[0]["feed_url"] == "https://ex.org/f.xml"
    assert chain[0]["basis"] == "feed_entry"


def test_registry_seed_confirms_only_the_entry_not_guessed_deep_links(monkeypatch):
    """A trusted entry URL is readable, but it does NOT authorise guessing deeper
    URLs on the same domain: those stay blocked by the URL confirmation gate."""
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    fetched: list[str] = []

    def fake_fetch(url, timeout=15.0, deadline=None):
        fetched.append(url)
        return "<html><body>What's New index page</body></html>"

    monkeypatch.setattr(agent, "safe_fetch", fake_fetch)
    completion = make_completion([
        {"tool": "read_page", "url": "https://docs.python.org/3/whatsnew/"},
        {"tool": "read_page", "url": "https://docs.python.org/3/whatsnew/3.13.html"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(
        gateway=FakeGateway(), completion=completion, question="Python 3.13 what's new",
        budget=AgentBudget(),
        registry_sources=(("python-docs-whatsnew", "https://docs.python.org/3/whatsnew/"),),
    )
    reads = [c for c in trace["calls"] if c.get("action", {}).get("tool") == "read_page"]
    assert reads[0]["result"].get("ok") is True, reads[0]
    assert reads[1]["result"].get("status") == "pending_url_confirmation"
    assert reads[1]["result"].get("reason") == "url_not_from_search_result"
    assert "https://docs.python.org/3/whatsnew/3.13.html" not in fetched


_EXCLUDED_FEED = ("<rss><channel><item><title>Python 3.15.0 (final) is here!</title>"
                  "<link>https://blog.python.org/3150-final</link></item></channel></rss>")


def _excluded_read_run(monkeypatch, **extra):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    monkeypatch.setattr(agent, "safe_fetch", lambda url, timeout=15.0, deadline=None: _EXCLUDED_FEED)
    completion = make_completion([
        {"tool": "feed", "url": "https://ex.org/f.xml"},
        {"tool": "read_page", "url": "https://blog.python.org/3150-final"},
        {"tool": "finish"},
    ])
    return run_tool_agent(gateway=FakeGateway(), completion=completion,
                          question="Python 3.15.0 入门教程", budget=AgentBudget(),
                          registry_sources=(("src", "https://ex.org/f.xml"),), **extra)


def test_read_gate_blocks_excluded_feed_entry(monkeypatch):
    trace = _excluded_read_run(monkeypatch)
    read_calls = [c for c in trace["calls"] if c.get("action", {}).get("tool") == "read_page"]
    assert read_calls and read_calls[0]["result"]["status"] == "entry_not_eligible"
    assert trace["reads"] == 0    # quota not consumed
    assert trace["bodies"] == []  # reader never called


def test_read_gate_not_bypassed_by_other_confirmation(monkeypatch):
    trace = _excluded_read_run(monkeypatch, initial_urls=("https://blog.python.org/3150-final",))
    read_calls = [c for c in trace["calls"] if c.get("action", {}).get("tool") == "read_page"]
    assert read_calls and read_calls[0]["result"]["status"] == "entry_not_eligible"
    assert trace["bodies"] == []


_FOLLOW_HTML = ('<html><body>'
                '<a href="/wiki/Train_interrupts">Train interrupts</a>'
                '<a href="https://evil.example/x">external</a>'
                '<a href="#top">skip</a>'
                '<a href="https://wiki.example/wiki/Schedule">Schedules</a>'
                '</body></html>')


def test_follow_lists_same_origin_links_only(monkeypatch):
    import src.web.research_tool_agent as agent
    import src.web.safe_http as sh

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    monkeypatch.setattr(sh, "safe_fetch_result", lambda url, **k: {"content": _FOLLOW_HTML})
    completion = make_completion([
        {"tool": "follow", "url": "https://wiki.example/"},
        {"tool": "read_page", "url": "https://wiki.example/wiki/Train_interrupts"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion, question="train interrupts",
                           budget=AgentBudget(), initial_urls=("https://wiki.example/",))
    follow_calls = [c for c in trace["calls"] if c.get("action", {}).get("tool") == "follow"]
    assert follow_calls and follow_calls[0]["result"]["status"] == "ok"
    urls = [link["url"] for link in follow_calls[0]["links"]]
    assert "https://wiki.example/wiki/Train_interrupts" in urls
    assert all("evil.example" not in u for u in urls)      # same-origin only
    assert all("#" not in u for u in urls)                 # fragments skipped
    # follow lists links but never auto-reads: the model must call read_page itself.
    assert trace["reads"] == 2  # 1 follow + 1 explicit read_page


def test_follow_ranks_links_by_question_not_document_order(monkeypatch):
    """A relevant article beyond the first five links must still be offered."""
    import src.web.research_tool_agent as agent
    import src.web.safe_http as sh

    html = (
        "<html><body>"
        '<a href="/cs">Cesky</a>'
        '<a href="/de">Deutsch</a>'
        '<a href="/fr">Francais</a>'
        '<a href="/Login">Log in</a>'
        '<a href="/category">Categories</a>'
        '<a href="/wiki/Train_interrupts">Train interrupts</a>'
        "</body></html>"
    )
    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    monkeypatch.setattr(sh, "safe_fetch_result", lambda url, **k: {"content": html})
    completion = make_completion([
        {"tool": "follow", "url": "https://wiki.example/"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(gateway=FakeGateway(), completion=completion,
                           question="Factorio train interrupts schedule",
                           budget=AgentBudget(), initial_urls=("https://wiki.example/",))
    follow = [c for c in trace["calls"] if c.get("action", {}).get("tool") == "follow"][0]
    urls = [link["url"] for link in follow["links"]]
    assert urls and urls[0].endswith("/wiki/Train_interrupts")
    assert follow["result"]["candidates"] >= 6          # every same-site link was considered
    # one fetch only: follow never reads the child pages itself
    assert trace["reads"] == 1


def test_reading_the_same_page_twice_does_not_spend_quota(monkeypatch):
    """A successful read is not repeated: the second attempt costs no read quota."""
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    prompts: list[str] = []
    actions = [
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ]

    class _GW:
        def __init__(self):
            self.reads = []

        def read(self, url, *, max_chars=6000, timeout=8.0):
            self.reads.append(url)
            return {"ok": True, "url": url,
                    "content": "train interrupts: trigger conditions and the schedule relation"}

    def completion(messages, **kwargs):
        prompts.append(messages[-1]["content"])
        return json.dumps(actions.pop(0))

    gw = _GW()
    trace = run_tool_agent(gateway=gw, completion=completion,
                           question="Factorio train interrupts",
                           budget=AgentBudget(), initial_urls=("https://example.org/a",))
    results = [c["result"] for c in trace["calls"]
               if (c.get("action") or {}).get("tool") == "read_page"]
    assert results[0].get("ok") is True
    assert results[1].get("status") == "already_read"
    assert trace["reads"] == 1 and len(gw.reads) == 1     # second attempt spent nothing
    assert any("still uncovered" in prompt for prompt in prompts)


def test_finish_reports_incomplete_coverage(monkeypatch):
    """A finish that leaves question terms uncovered is reported as incomplete, not done."""
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    actions = [{"tool": "read_page", "url": "https://example.org/a"}, {"tool": "finish"}]

    class _GW:
        def read(self, url, *, max_chars=6000, timeout=8.0):
            return {"ok": True, "url": url, "content": "train interrupts only"}

    def completion(messages, **kwargs):
        return json.dumps(actions.pop(0))

    trace = run_tool_agent(gateway=_GW(), completion=completion,
                           question="Factorio train interrupts schedule",
                           budget=AgentBudget(), initial_urls=("https://example.org/a",))
    assert trace["stop_reason"] == "finished_incomplete"
    assert trace["coverage_audit"]["missing"]
    assert trace["coverage_audit"]["complete"] is False
    finish = [c for c in trace["calls"] if (c.get("action") or {}).get("tool") == "finish"][0]
    assert finish["result"]["status"] == "finished_incomplete"
    assert finish["coverage_audit"]["missing"]


def test_identical_body_from_two_urls_is_flagged_and_not_double_counted(monkeypatch):
    """Same text behind a different URL adds no coverage and is reported."""
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    actions = [
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "read_page", "url": "https://example.org/b"},
        {"tool": "finish"},
    ]

    class _GW:
        def read(self, url, *, max_chars=6000, timeout=8.0):
            return {"ok": True, "url": url, "content": "train interrupts explained"}

    def completion(messages, **kwargs):
        return json.dumps(actions.pop(0))

    trace = run_tool_agent(gateway=_GW(), completion=completion, question="train interrupts",
                           budget=AgentBudget(),
                           initial_urls=("https://example.org/a", "https://example.org/b"))
    reads = [c["result"] for c in trace["calls"]
             if (c.get("action") or {}).get("tool") == "read_page"]
    assert reads[0].get("ok") is True
    assert reads[1].get("duplicate_body") is True
    assert len(trace["coverage_log"]) == 1        # only the first body contributed


def test_sub_goals_track_missing_and_block_a_false_finish(monkeypatch):
    """A sub-goal without supporting text stays 'missing' and forces finished_incomplete."""
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)
    actions = [{"tool": "read_page", "url": "https://example.org/a"}, {"tool": "finish"}]

    class _GW:
        def read(self, url, *, max_chars=6000, timeout=8.0):
            return {"ok": True, "url": url, "content": "the liberty and capture basics"}

    def completion(messages, **kwargs):
        return json.dumps(actions.pop(0))

    trace = run_tool_agent(gateway=_GW(), completion=completion,
                           question="go capture and ko rule",
                           sub_goals=(("liberties and capture", ("liberty", "capture")),
                                      ("ko rule", ("ko rule", "recapture"))),
                           budget=AgentBudget(), initial_urls=("https://example.org/a",))
    audit = trace["coverage_audit"]
    assert audit["sub_goals"]["liberties and capture"]["status"] == "explored"
    assert audit["sub_goals"]["liberties and capture"]["url"].endswith("/a")
    assert audit["sub_goals"]["ko rule"]["status"] == "missing"
    assert audit["pending_sub_goals"] == ["ko rule"]
    assert trace["stop_reason"] == "finished_incomplete"
    assert audit["complete"] is False


def test_safe_fetch_result_structured(monkeypatch):
    import gzip

    import src.web.safe_http as sh

    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kwargs: ["1.2.3.4"])
    packed = gzip.compress(b"<html>hi</html>")
    monkeypatch.setattr(
        sh, "http_get_raw",
        lambda url, host, ip, *, timeout, max_bytes=sh.MAX_BYTES:
        (200, {"content-type": "text/html", "content-encoding": "gzip"}, packed, False),
    )
    result = sh.safe_fetch_result("https://ex.org/a", timeout=5)
    assert result["status"] == 200 and result["final_url"] == "https://ex.org/a"
    assert result["content_type"] == "text/html" and result["content_encoding"] == "gzip"
    assert result["raw"] == packed and result["truncated"] is False
    assert result["text"] == "<html>hi</html>"      # bounded gzip decode applied


def test_safe_fetch_result_reports_truncation(monkeypatch):
    import src.web.safe_http as sh

    monkeypatch.setattr(sh, "resolve_public_ips", lambda host, **kwargs: ["1.2.3.4"])
    monkeypatch.setattr(sh, "http_get_raw", lambda url, host, ip, *, timeout, max_bytes=300_000: (200, {}, b"x" * 10, True))
    with pytest.raises(sh.SafeFetchRefusal):
        sh.safe_fetch_result("https://ex.org/a", timeout=5)


def test_safe_fetch_result_blocks_private_without_request(monkeypatch):
    import src.web.safe_http as sh

    called: list[int] = []

    def fail(_host, **kwargs):
        raise ValueError("unsafe_target")

    monkeypatch.setattr(sh, "resolve_public_ips", fail)
    monkeypatch.setattr(sh, "http_get_raw", lambda *a, **k: called.append(1))
    with pytest.raises(ValueError):
        sh.safe_fetch_result("https://ex.org/a", timeout=5)
    assert called == []
