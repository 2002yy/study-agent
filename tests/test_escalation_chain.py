"""Escalation chain: it must be able to fire, and useless churn must never earn it."""

from __future__ import annotations

import json

from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway

GOAL = "快照机制、清理代价"
ARTICLE = ("多版本并发控制通过保留旧版本行来实现一致性：因为每个事务读取自己的快照，"
           "读操作不会阻塞写操作。代价是旧版本必须清理，否则会造成表膨胀。"
           "系统需要定期回收不再可见的行版本，否则查询会逐渐变慢。")
NEXT_TIER = AgentBudget(max_rounds=16, max_searches=6, max_reads=8, hard_seconds=120.0)


def _run(actions: list[dict], *, body: str = ARTICLE, initial: tuple[str, ...] = ()) -> dict:
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": body}
    queue = list(actions)

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    return run_tool_agent(
        gateway=gateway, completion=completion, question="快照机制与代价",
        budget=AgentBudget(max_rounds=3, max_searches=1, max_reads=1, hard_seconds=30.0),
        escalation_budgets=(NEXT_TIER,), sub_goals=((GOAL, ("快照", "代价")),),
        initial_urls=initial)


def test_the_chain_fires_when_progress_is_real_and_work_remains():
    """A run with genuine progress, an unresolved goal and an unread candidate escalates."""
    trace = _run([
        {"tool": "read_page", "url": "https://example.org/a"},      # progress: new coverage
        {"tool": "search", "query": "清理机制"},                     # keep taking turns
        {"tool": "search", "query": "回收机制"},
        {"tool": "search", "query": "膨胀机制"},
    ], initial=("https://example.org/a", "https://example.org/b"))
    assert trace["escalations"], "the monotonically larger tier must be reachable"
    assert trace["escalations"][0] == NEXT_TIER.max_rounds


def test_useless_repeated_reads_never_earn_an_escalation():
    """The negative control: churn on an already-read page is not progress."""
    trace = _run([
        {"tool": "read_page", "url": "https://example.org/a"},      # read once (progress)
        {"tool": "read_page", "url": "https://example.org/a"},      # refused: already_read
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "read_page", "url": "https://example.org/a"},
    ], initial=("https://example.org/a", "https://example.org/b"))
    statuses = [(call.get("result") or {}).get("status") for call in trace["calls"]]
    assert statuses.count("already_read") >= 2     # the churn really happened
    assert trace["escalations"] == []              # and it earned nothing
