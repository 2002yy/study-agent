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
ARTICLE_BODY = (
    "漏斗是一种可以用来捕捉物品实体或转入转出容器中物品的方块，它会从上方吸收物品。"
    "漏斗可以把物品送到它朝向的容器中，因此常用于自动化排序与物品分类装置。"
    "漏斗的合成需要五个铁锭与一个箱子，代价是铁锭的数量较多。"
    "玩家可以用漏斗搭建简单的物品分类装置，这也是它最常见的用途。"
    "关于漏斗的传输速率与朝向，正文段落给出了详细的说明与示例。"
    "投掷器是一种可以将物品向前弹出的方块，它会将物品吐出而不是送入容器。")

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


def test_the_site_scoped_query_actually_executes():
    """Route two must be a real request, not just a generated string.

    With no entry naming the subject, the run still knows an allowed host: it must ASK that host
    for the subject, through the ordinary search path (quota, dedup, request all counted).
    """
    gateway = FakeGateway(results=[{"title": "站点首页", "url": "https://example.org/",
                                    "snippet": "首页 导航"}])
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": GENERIC}
    queue = [{"tool": "search", "query": "漏斗投掷器"},
             {"tool": "read_page", "url": "https://example.org/"},
             {"tool": "finish", "reason": "done"}]

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="漏斗与投掷器的区别",
        budget=AgentBudget(max_rounds=6, max_searches=3, max_reads=4, hard_seconds=60.0),
        sub_goals=((GOAL, ("漏斗", "代价")),), initial_urls=("https://example.org/",),
        discovery_hops=True)

    scoped = [call for call in _agent_calls(trace) if call["action"]["tool"] == "search"]
    assert scoped, "the site-scoped route never executed"
    query = scoped[0]["action"]["query"]
    assert "site:example.org" in query and "漏斗" in query
    assert query in gateway.searches        # a real request was issued, not a suggestion


def test_mc_shape_reserves_the_last_search_for_recovery():
    """Four homepage-only searches must not exhaust the budget before recovery can run.

    The reserve is established from the first failed search, so ordinary searches stop at three
    and the fourth slot belongs to the deterministic site-scoped query.
    """
    gateway = FakeGateway(results=[{"title": "站点首页", "url": "https://example.org/",
                                    "snippet": "首页 导航"}])
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": GENERIC}
    queue = [{"tool": "search", "query": "q1"},
             {"tool": "search", "query": "q2"},
             {"tool": "search", "query": "q3"},
             {"tool": "search", "query": "q4"},          # must NOT get the reserved slot
             {"tool": "read_page", "url": "https://example.org/"},
             {"tool": "finish", "reason": "done"}]

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="漏斗与投掷器的区别",
        budget=AgentBudget(max_rounds=10, max_searches=4, max_reads=6, hard_seconds=90.0),
        sub_goals=((GOAL, ("漏斗", "代价")),), initial_urls=("https://example.org/",),
        discovery_hops=True)

    reasons = [c["result"].get("reason") for c in trace["calls"]
               if (c.get("result") or {}).get("status") == "quota_exceeded"]
    assert "search_reserved_for_recovery" in reasons, "the reserve never protected a slot"
    scoped = [c for c in _agent_calls(trace) if c["action"]["tool"] == "search"]
    assert scoped and "site:example.org" in scoped[0]["action"]["query"]
    assert len(gateway.searches) <= 4            # the total budget was never exceeded
    assert scoped[0]["action"]["query"] in gateway.searches


def test_an_article_search_reserves_nothing_for_recovery():
    """PostgreSQL shape: usable article results mean the fourth search stays ordinary."""
    gateway = FakeGateway(results=ARTICLE_HIT)
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": GENERIC}
    queue = [{"tool": "search", "query": "q1"}, {"tool": "search", "query": "q2"},
             {"tool": "search", "query": "q3"}, {"tool": "search", "query": "q4"},
             {"tool": "finish", "reason": "done"}]

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="漏斗与投掷器的区别",
        budget=AgentBudget(max_rounds=8, max_searches=4, max_reads=6, hard_seconds=90.0),
        sub_goals=((GOAL, ("漏斗", "代价")),), initial_urls=("https://example.org/",),
        discovery_hops=True)

    assert trace["auto_hops"] == 0
    assert len(gateway.searches) == 4            # every ordinary search was allowed through
    assert not [c for c in trace["calls"]
                if (c.get("result") or {}).get("reason") == "search_reserved_for_recovery"]


def test_the_reserve_is_released_once_material_arrives():
    """A reservation that can no longer be spent must not keep blocking ordinary searches."""
    gateway = FakeGateway(results=[{"title": "站点首页", "url": "https://example.org/",
                                    "snippet": "首页 导航"}])
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": ARTICLE_BODY}
    queue = [{"tool": "search", "query": "q1"},
             {"tool": "read_page", "url": "https://example.org/"},
             {"tool": "search", "query": "q2"},
             {"tool": "search", "query": "q3"},
             {"tool": "search", "query": "q4"},
             {"tool": "finish", "reason": "done"}]

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="漏斗与投掷器的区别",
        budget=AgentBudget(max_rounds=10, max_searches=4, max_reads=6, hard_seconds=90.0),
        sub_goals=((GOAL, ("漏斗", "代价")),), initial_urls=("https://example.org/",),
        discovery_hops=True)

    assert not _agent_calls(trace)               # nothing to recover once material is in hand
    assert len(gateway.searches) == 4            # the released slot was usable again


def test_the_recovery_host_choice_is_deterministic():
    """Two hosts, one run repeatable: the host that produced more entries wins, ties by name."""
    from src.web.research_tool_agent import _site_scoped_query

    twice = [
        _site_scoped_query(["漏斗"], {"https://b.example/", "https://a.example/",
                                      "https://a.example/Category:漏斗"},
                           set(), ["https://a.example/Category:漏斗"])
        for _ in range(2)]
    assert twice[0] == twice[1] == "漏斗 site:a.example"
    assert _site_scoped_query(["漏斗"], set(), set(), []) == ""      # nothing confirmable


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


def test_a_search_with_no_relevant_host_triggers_a_subject_keyed_recovery():
    """An unrelated result set is a SEARCH FAILURE: recover using the question's own words."""
    gateway = FakeGateway(results=[{"title": "抖音", "url": "https://www.douyin.com/",
                                    "snippet": "短视频平台"}])
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": GENERIC}
    queue = [{"tool": "search", "query": "PEP 701 python 3.12"},
             {"tool": "read_page", "url": "https://www.douyin.com/"},
             {"tool": "finish", "reason": "done"}]

    def completion(**_kwargs):
        return json.dumps(queue.pop(0) if queue else {"tool": "finish"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion,
        question="Python 3.12 的 PEP 701 f-string 有什么不兼容风险？",
        budget=AgentBudget(max_rounds=8, max_searches=3, max_reads=4, hard_seconds=60.0),
        sub_goals=(("PEP 701 的不兼容风险", ("PEP", "兼容")),),
        initial_urls=("https://www.douyin.com/",), discovery_hops=True)

    recovered = [call for call in _agent_calls(trace)
                 if call["action"]["tool"] == "search"]
    assert recovered, "the reserved slot must be used for a recovery search"
    assert "pep" in recovered[0]["action"]["query"].casefold()
    assert len(gateway.searches) <= 3
