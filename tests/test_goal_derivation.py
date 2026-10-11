"""M4-C4 / C3: the real entry derives sub-goals from the question itself."""
from __future__ import annotations

import json

from src.web.link_discovery import derive_sub_goals, question_terms
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway


def test_two_clause_question_splits_into_two_goals():
    question = "PostgreSQL 的 MVCC 如何避免读写互相阻塞？它带来的主要代价是什么？"
    goals = derive_sub_goals(question)
    assert len(goals) == 2
    labels = [label for label, _terms in goals]
    assert all(label in question for label in labels)      # labels come from the question
    joined = " ".join(" ".join(terms) for _label, terms in goals)
    assert "阻塞" in joined and "代价" in joined


def test_terms_are_a_subset_of_the_question_tokens():
    """Derivation may not smuggle in knowledge the question does not carry."""
    question = "Minecraft 中漏斗与投掷器在物品传输上的区别是什么？如何用于自动化排序？"
    allowed = question_terms(question)
    goals = derive_sub_goals(question)
    assert goals
    for _label, terms in goals:
        assert set(terms) <= allowed, set(terms) - allowed


def test_single_goal_question_is_not_split():
    assert derive_sub_goals("Python 3.13 是什么时候发布的？") == ()
    assert derive_sub_goals("") == ()


def test_agent_derives_goals_when_none_are_supplied():
    seen: list[dict] = []
    seq = [{"tool": "search", "query": "s"}, {"tool": "finish"}]

    def completion(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps(seq.pop(0))

    trace = run_tool_agent(
        gateway=FakeGateway(), completion=completion,
        question="PostgreSQL 的 MVCC 如何避免读写互相阻塞？它带来的主要代价是什么？",
        budget=AgentBudget(max_rounds=2, max_searches=2, max_reads=2, hard_seconds=30.0),
    )
    assert len(trace["derived_sub_goals"]) == 2
    # the derived goals drive the per-round gap targeting
    assert any("MISSING goals" in (ctx.get("budget_state") or "") for ctx in seen)


def test_explicit_sub_goals_win_over_derivation():
    seen: list[dict] = []

    def completion(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps({"tool": "finish"})

    trace = run_tool_agent(
        gateway=FakeGateway(), completion=completion, question="a question with gaps",
        budget=AgentBudget(), sub_goals=(("explicit", ("gap",)),),
    )
    assert trace["derived_sub_goals"] == []
    assert any("explicit" in (ctx.get("budget_state") or "") for ctx in seen)
