"""B-Search TOC + Action Budget: content-level index detection and the conditional
search reserve (no new rounds are added)."""
from __future__ import annotations

import json

import pytest

from src.application.research_shadow_seam import (
    BSEARCH_SHADOW_BUDGET_SECONDS,
    BSEARCH_SHADOW_MAX_READS,
    BSEARCH_SHADOW_MAX_ROUNDS,
    BSEARCH_SHADOW_MAX_SEARCHES,
    BUDGET_TIERS,
    DEFAULT_TIER,
    tier_budget,
)
from src.web.link_discovery import looks_like_navigation
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway


@pytest.fixture(autouse=True)
def _assume_public_hosts(monkeypatch):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)


#: The real reader collapses whitespace, so this mirrors an extracted version/index page.
TOC_TEXT = "PostgreSQL 18 发布 文档 支持的版本: 18 / 17 / 16 / 15 / 14 / 13 / 12 / 11 / 10"
PROSE_TEXT = (
    "多版本并发控制让每个事务看到一致的快照，因此读操作不会阻塞写操作，写操作也不会阻塞读"
    "操作；PostgreSQL 通过保留旧版本行来实现这一点。" * 3
)


def _completion(actions, seen):
    seq = list(actions)

    def run(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps(seq.pop(0))

    return run


def test_looks_like_navigation_distinguishes_index_from_prose():
    assert looks_like_navigation(TOC_TEXT) is True
    assert looks_like_navigation(PROSE_TEXT) is False
    assert looks_like_navigation("") is False
    # a long mechanism page is never an index, even with separators
    assert looks_like_navigation(PROSE_TEXT * 10) is False
    # prose that merely mentions a version once is not navigation
    assert looks_like_navigation("PostgreSQL 17 引入了改进，并保持了兼容性。") is False


def test_navigation_read_is_marked_and_redirected():
    """A read that returns index-shaped content is labelled and the model is told to
    follow/read a real candidate instead."""
    gateway = FakeGateway()
    seen: list[dict] = []
    completion = _completion([
        {"tool": "read_page", "url": "https://example.org/index"},
        {"tool": "finish"},
    ], seen)
    # make the read return navigation-shaped text
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url,
        "content": "PostgreSQL 18 发布 支持的版本: 18 / 17 / 16 / 15 / 14 / 13",
    }
    trace = run_tool_agent(gateway=gateway, completion=completion, question="q",
                           budget=AgentBudget(), initial_urls=("https://example.org/index",))
    read_call = [c for c in trace["calls"] if c["action"].get("tool") == "read_page"][0]
    assert read_call.get("page_kind") == "navigation"


def test_budget_guide_tells_the_model_to_stop_searching():
    """The reserve is an instruction (a refusal would spend the round it saves)."""
    gateway = FakeGateway()
    seen: list[dict] = []
    completion = _completion(
        [{"tool": "search", "query": f"q{i}"} for i in range(4)]
        + [{"tool": "read_page", "url": "https://example.org/a"}, {"tool": "finish"}],
        seen,
    )
    trace = run_tool_agent(gateway=gateway, completion=completion, question="q",
                           budget=AgentBudget())
    guides = [ctx for ctx in seen
              if "do NOT search again" in json.dumps(ctx.get("budget_state") or "")]
    assert guides, seen[-1].get("budget_state")
    # no round was burned by a refusal: the fourth search still executed
    search_calls = [c for c in trace["calls"] if c["action"].get("tool") == "search"]
    assert len(search_calls) == 4
    assert all(c["result"].get("status") == "ok" for c in search_calls)


def test_budget_guide_is_absent_without_candidates():
    """A topic with no confirmed candidates yet must not be told to stop searching."""
    gateway = FakeGateway()
    gateway._results = []  # FakeGateway treats an empty list as "use the default"
    seen: list[dict] = []
    completion = _completion(
        [{"tool": "search", "query": f"q{i}"} for i in range(4)] + [{"tool": "finish"}],
        seen,
    )
    trace = run_tool_agent(gateway=gateway, completion=completion, question="q",
                           budget=AgentBudget())
    assert not [ctx for ctx in seen
                if "do NOT search again" in json.dumps(ctx.get("budget_state") or "")]
    assert trace["searches"] == 4


def _nav_gateway(text: str) -> FakeGateway:
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": text}
    return gateway


def test_navigation_page_does_not_contribute_coverage():
    """A navigation page's keywords must not count as mechanism evidence."""
    trace = run_tool_agent(
        gateway=_nav_gateway(TOC_TEXT), question="PostgreSQL 版本",
        completion=_completion([{"tool": "read_page", "url": "https://example.org/toc"},
                                {"tool": "finish"}], []),
        budget=AgentBudget(), initial_urls=("https://example.org/toc",))
    assert trace["coverage_log"] == []
    assert trace["coverage_audit"]["covered"] == []


def test_read_navigation_becomes_a_pending_follow_and_reread_is_redirected():
    seen: list[dict] = []
    trace = run_tool_agent(
        gateway=_nav_gateway(TOC_TEXT), question="PostgreSQL 版本 说明",
        completion=_completion([{"tool": "read_page", "url": "https://example.org/toc"},
                                {"tool": "read_page", "url": "https://example.org/toc"},
                                {"tool": "finish"}], seen),
        budget=AgentBudget(), initial_urls=("https://example.org/toc",))
    # the next round is told which navigation page still needs following
    assert any((ctx.get("next_follow") or []) == ["https://example.org/toc"] for ctx in seen)
    # a second read of a known navigation page gets the explicit instruction
    assert "KNOWN navigation page" in json.dumps(trace["observations"], ensure_ascii=False)
    # and the navigation verdict is recorded on the read itself
    assert [c.get("page_kind") for c in trace["calls"]
            if c["action"].get("tool") == "read_page"][0] == "navigation"


def test_budget_guide_fires_before_the_third_search():
    seen: list[dict] = []
    run_tool_agent(
        gateway=FakeGateway(), question="q",
        completion=_completion([{"tool": "search", "query": f"q{i}"} for i in range(3)]
                               + [{"tool": "finish"}], seen),
        budget=AgentBudget())
    guides = [i for i, ctx in enumerate(seen)
              if "do NOT search again" in json.dumps(ctx.get("budget_state") or "")]
    assert guides and guides[0] <= 2          # warned by the third model call
    assert any("overrides the generic" in json.dumps(ctx.get("budget_state") or "")
               for ctx in seen)


def test_short_numbered_guides_are_not_navigation():
    assert looks_like_navigation(
        "第1步 打开设置 第2步 选择语言 第3步 保存 第4步 重启 第5步 完成") is False
    assert looks_like_navigation("步骤 1 2 3 4 5 6 7 8") is False


def test_budget_tiers_and_default():
    """The tier table is the configuration entry point; standard is the default."""
    assert BUDGET_TIERS["quick"] == (4, 2, 2, 20.0)
    assert BUDGET_TIERS["standard"] == (8, 4, 5, 40.0)
    assert BUDGET_TIERS["deep"] == (12, 6, 8, 75.0)
    assert DEFAULT_TIER == "standard"
    assert tier_budget("deep") == (12, 6, 8, 75.0)
    assert (BSEARCH_SHADOW_MAX_ROUNDS, BSEARCH_SHADOW_MAX_SEARCHES,
            BSEARCH_SHADOW_MAX_READS, BSEARCH_SHADOW_BUDGET_SECONDS) == BUDGET_TIERS["standard"]
    # the low-level tool default is separate and unchanged
    default = AgentBudget()
    assert (default.max_rounds, default.max_searches, default.max_reads) == (6, 4, 3)


def test_escalation_extends_the_same_run_without_restarting():
    """Unresolved goals + an actionable candidate extend the run once; state is kept."""
    gateway = FakeGateway()
    seen: list[dict] = []
    completion = _completion([
        {"tool": "search", "query": "first"},
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "read_page", "url": "https://example.org/b"},   # after escalation
        {"tool": "finish"},
    ], seen)
    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="q",
        budget=AgentBudget(max_rounds=2, max_searches=2, max_reads=3, hard_seconds=30.0),
        escalation_budget=AgentBudget(max_rounds=4, max_searches=4, max_reads=5,
                                      hard_seconds=30.0),
        sub_goals=(("a", ("topic",)),),
    )
    assert trace["escalated"] is True
    assert len(trace["calls"]) == 4                     # it continued past round 2
    tools = [c["action"]["tool"] for c in trace["calls"]]
    assert tools.count("search") == 1                   # nothing was re-searched


def test_escalation_needs_unresolved_goals_and_an_actionable_state():
    gateway = FakeGateway()
    gateway._results = []                               # no candidates -> nothing to act on
    completion = _completion([{"tool": "search", "query": "s"}], [])
    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="q",
        budget=AgentBudget(max_rounds=1, max_searches=2, max_reads=1, hard_seconds=30.0),
        escalation_budget=AgentBudget(max_rounds=3, max_searches=3, max_reads=3,
                                      hard_seconds=30.0),
        sub_goals=(("a", ("topic",)),),
    )
    assert trace["escalated"] is False                  # no actionable candidate
