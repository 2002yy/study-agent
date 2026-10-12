"""Discovery Recovery: opt-in, triggered by search failure, bounded, and accounted for."""

from __future__ import annotations

import json

from src.web.research_tool_agent import (MAX_AUTO_HOPS, AgentBudget, _auto_hop_target,
                                         run_tool_agent)
from tests.test_research_tool_agent import FakeGateway

GENERIC = ("这是一段与目标无关的通用介绍文字，用来填充页面内容以便通过正文资格检查。"
           "它描述了站点自身的历史与组织结构，并没有说明任何机制细节。"
           "读者可以在这里找到导航链接与分类入口。")
GOAL = "漏斗机制、代价"
SIDES = ("漏斗", "投掷器")
ARTICLE_BODY = ("漏斗是一种可以捕捉物品实体的方块，它会从上方吸收物品。"
                "漏斗可以把物品送到它朝向的容器中，因此常用于自动化排序。")

# The measured failure shape: the index answers with a site entry and no [article] at all.
ENTRY_ONLY = [{"title": "分类：漏斗", "url": "https://example.org/Category:漏斗",
               "snippet": "分类 导航 首页"}]
ARTICLE_HIT = [{"title": "漏斗", "url": "https://example.org/w/漏斗",
                "snippet": "漏斗是一种方块"}]


def _run(actions: list[dict], *, hops: bool, initial: tuple[str, ...],
         body: str = GENERIC, goal: str = GOAL, results: list[dict] | None = None) -> dict:
    gateway = FakeGateway(results=results or ENTRY_ONLY)
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": body}
    queue = list(actions)

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    return run_tool_agent(
        gateway=gateway, completion=completion, question="漏斗与投掷器的区别",
        budget=AgentBudget(max_rounds=6, max_searches=2, max_reads=4, hard_seconds=60.0),
        sub_goals=((goal, ("漏斗", "代价")),), initial_urls=initial,
        discovery_hops=hops)


def _agent_calls(trace: dict) -> list[dict]:
    return [call for call in trace["calls"] if call.get("agent_initiated")]


def test_hops_are_off_by_default():
    """The switch OFF must leave behaviour and cost exactly as they were."""
    trace = _run([
        {"tool": "search", "query": "漏斗"},
        {"tool": "search", "query": "投掷器"},
        {"tool": "finish"},
    ], hops=False, initial=("https://example.org/",))
    assert trace["auto_hops"] == 0
    assert not _agent_calls(trace)


def test_a_relevant_site_entry_produces_one_bounded_hop():
    trace = _run([
        {"tool": "search", "query": "漏斗与投掷器"},
        {"tool": "read_page", "url": "https://example.org/"},
        {"tool": "finish", "reason": "done"},
    ], hops=True, initial=("https://example.org/",))
    hops = _agent_calls(trace)
    assert 1 <= trace["auto_hops"] <= MAX_AUTO_HOPS and hops
    follow = [c for c in hops if c["action"]["tool"] == "follow"]
    assert follow and follow[0]["action"]["url"] == ENTRY_ONLY[0]["url"]
    # Whatever else it does stays agent-initiated and pre-declared, never a model decision.
    for call in hops:
        assert call["action"]["reason"] in {"auto_discovery_hop", "auto_site_scoped_search"}
    assert trace["cost"]["network_requests"] >= 1
    assert all(call["error"] == "" for call in follow)


def test_an_article_search_never_triggers_discovery():
    """The PostgreSQL shape: the index already returned an article, so nothing may be nudged.

    This is the regression guard for the case that made an earlier revision detour a run whose
    search results were perfectly usable.
    """
    trace = _run([
        {"tool": "search", "query": "漏斗与投掷器"},
        {"tool": "finish", "reason": "done"},
    ], hops=True, initial=("https://example.org/",), results=ARTICLE_HIT)
    assert trace["auto_hops"] == 0
    assert not _agent_calls(trace)


def test_an_open_goal_without_a_failed_search_is_not_enough():
    """No search yet means no evidence of failure: discovery recovery stays silent."""
    trace = _run([
        {"tool": "read_page", "url": "https://example.org/"},
        {"tool": "finish", "reason": "done"},
    ], hops=True, initial=("https://example.org/",))
    assert trace["auto_hops"] == 0
    assert not _agent_calls(trace)


def test_a_precise_article_is_read_instead_of_hopping():
    """A confirmed ARTICLE matching a missing subject takes priority over navigation."""
    picked = _auto_hop_target(
        confirmed={"https://example.org/w/漏斗"}, read_pages={}, exclusions={}, basis={},
        labels={}, goals={GOAL: ("漏斗", "代价")}, sides_by_goal={GOAL: SIDES},
        hops_used=0, hopped=set(), searches=1, reads_left=3, remaining_seconds=90.0,
        has_material=False)
    assert picked == ""            # the article is the thing to read, not a reason to wander


def test_a_containing_name_is_not_the_entity():
    """Precision: "漏斗矿车" is a different article, so it is never treated as the subject."""
    assert _auto_hop_target(
        confirmed={"https://example.org/w/漏斗矿车"}, read_pages={}, exclusions={}, basis={},
        labels={"https://example.org/w/漏斗矿车": "漏斗矿车"},
        goals={GOAL: ("漏斗",)}, sides_by_goal={GOAL: SIDES}, hops_used=0, hopped=set(),
        searches=1, reads_left=4, remaining_seconds=90.0, has_material=False) == ""


def test_the_hop_never_exceeds_its_bound_or_repeats_an_entry():
    target = "https://example.org/Category:漏斗"
    another = "https://example.org/Category:投掷器"
    first = _auto_hop_target(
        confirmed={target, another}, read_pages={}, exclusions={}, basis={}, labels={},
        goals={GOAL: ("漏斗",)}, sides_by_goal={GOAL: SIDES}, hops_used=0, hopped=set(),
        searches=1, reads_left=4, remaining_seconds=90.0, has_material=False)
    assert first
    second = _auto_hop_target(
        confirmed={target, another}, read_pages={}, exclusions={}, basis={}, labels={},
        goals={GOAL: ("漏斗",)}, sides_by_goal={GOAL: SIDES}, hops_used=1, hopped={first},
        searches=1, reads_left=4, remaining_seconds=90.0, has_material=False)
    assert second and second != first
    exhausted = _auto_hop_target(
        confirmed={target}, read_pages={}, exclusions={}, basis={}, labels={},
        goals={GOAL: ("漏斗",)}, sides_by_goal={GOAL: SIDES}, hops_used=MAX_AUTO_HOPS,
        hopped={target}, searches=1, reads_left=4, remaining_seconds=90.0, has_material=False)
    assert exhausted == ""


def test_an_unrelated_site_entry_is_not_hopped():
    """Relevance is required: an entry naming no missing subject is never a target."""
    assert _auto_hop_target(
        confirmed={"https://minecraft.example.org/"}, read_pages={}, exclusions={}, basis={},
        labels={}, goals={GOAL: ("漏斗",)}, sides_by_goal={GOAL: SIDES}, hops_used=0,
        hopped=set(), searches=1, reads_left=4, remaining_seconds=90.0,
        has_material=False) == ""


def test_a_run_that_already_holds_material_never_hops():
    """With eligible material in hand, navigation would be a detour - even after a bad search."""
    trace = _run([
        {"tool": "search", "query": "漏斗与投掷器"},
        {"tool": "read_page", "url": "https://example.org/Category:漏斗"},
        {"tool": "finish", "reason": "done"},
    ], hops=True, initial=("https://example.org/Category:漏斗",), body=ARTICLE_BODY)
    assert not _agent_calls(trace)
