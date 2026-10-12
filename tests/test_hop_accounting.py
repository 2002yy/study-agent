"""An agent-initiated discovery action must not inflate model calls or research decisions."""

from __future__ import annotations

import json

from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway

GENERIC = ("这是一段与目标无关的通用介绍文字，用来填充页面内容以便通过正文资格检查。"
           "它描述了站点自身的历史与组织结构，并没有说明任何机制细节。"
           "读者可以在这里找到导航链接与分类入口。")
# The measured failure shape that licenses discovery recovery: an entry and no article.
ENTRY_ONLY = [{"title": "分类：漏斗", "url": "https://example.org/Category:漏斗",
               "snippet": "分类 导航 首页"}]


def test_hop_rounds_are_not_counted_as_model_calls_or_decisions():
    gateway = FakeGateway(results=ENTRY_ONLY)
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": GENERIC}
    seen = {"completions": 0}
    queue = [{"tool": "search", "query": "漏斗与投掷器"},
             {"tool": "read_page", "url": "https://example.org/"},
             {"tool": "finish", "reason": "done"}]

    def completion(**_kwargs):
        seen["completions"] += 1
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="漏斗与投掷器的区别",
        budget=AgentBudget(max_rounds=6, max_searches=2, max_reads=4, hard_seconds=60.0),
        sub_goals=(("漏斗机制、代价", ("漏斗", "代价")),),
        initial_urls=("https://example.org/",), discovery_hops=True)

    hops = [call for call in trace["calls"] if call.get("agent_initiated")]
    assert 1 <= trace["auto_hops"] <= 2 and hops     # discovery really happened
    # The model was asked exactly as often as it was actually prompted: a hop round asks nothing.
    assert trace["cost"]["model_calls"] == seen["completions"]
    assert trace["cost"]["research_decisions"] == seen["completions"]
