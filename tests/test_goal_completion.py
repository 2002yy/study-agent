"""Goal completion from necessary requirements, follow-ups for partial goals, budget caps."""

from __future__ import annotations

import json

from src.web.link_discovery import answer_items
from src.web.research_claim_verifier import ClaimVerdict, verify_claims
from src.web.research_gap_planner import plan_followups, uncovered_items
from src.web.research_tool_agent import (HARD_MODEL_CALL_CAP, HARD_WALL_SECONDS, AgentBudget,
                                         run_tool_agent)
from tests.test_research_tool_agent import FakeGateway
from tests.test_evidence_loop import MECHANISM


def _verdict(goal: str, covers: tuple[int, ...] = (), verdict: str = "supported") -> ClaimVerdict:
    return ClaimVerdict(goal_id=goal, claim="c", source_id="S1", verdict=verdict,
                        covers=covers)


def test_answer_items_splits_a_compound_goal_and_keeps_a_simple_one():
    assert answer_items("为什么不阻塞、主要代价是什么") == ("为什么不阻塞", "主要代价是什么")
    assert answer_items("PostgreSQL 的 MVCC 如何避免读写互相阻塞") == \
        ("PostgreSQL 的 MVCC 如何避免读写互相阻塞",)


def test_a_supported_claim_covering_one_requirement_leaves_the_other_uncovered():
    goal = "为什么不阻塞、主要代价是什么"
    verdicts = [_verdict(goal, covers=(0,))]
    assert uncovered_items(goal, verdicts) == [(1, "主要代价是什么")]


def test_followups_are_planned_for_a_partial_goal():
    """A goal with one correct claim is not finished: the missing requirement is asked for."""
    goal = "为什么不阻塞、主要代价是什么"
    verdicts = [_verdict(goal, covers=(0,))]
    planned = plan_followups(verdicts=verdicts, goals={goal: ("mvcc", "快照")})
    assert len(planned) == 1 and planned[0]["goal_id"] == goal
    assert planned[0]["query"]


def test_followups_stop_once_every_requirement_is_covered():
    goal = "为什么不阻塞、主要代价是什么"
    verdicts = [_verdict(goal, covers=(0, 1))]
    assert plan_followups(verdicts=verdicts, goals={goal: ("mvcc",)}) == []


def test_escalation_cannot_extend_the_wall_clock_past_the_global_cap():
    """A 600-second escalation tier must not reopen a bigger clock than the hard cap."""
    gateway = FakeGateway()
    calls = {"n": 0}

    def completion(**_kwargs):
        calls["n"] += 1
        return json.dumps({"tool": "finish", "reason": "done"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="Python 是什么？",
        budget=AgentBudget(max_rounds=2, max_searches=1, max_reads=1, hard_seconds=0.5),
        escalation_budgets=(AgentBudget(max_rounds=40, max_searches=20, max_reads=20,
                                        hard_seconds=600.0),),
        initial_urls=("https://example.org/a",))
    assert trace["wall_budget_seconds"] <= HARD_WALL_SECONDS
    assert trace["cost"]["model_calls"] <= HARD_MODEL_CALL_CAP


def test_verifier_records_requirement_coverage_from_a_real_path():
    """The verification call returns which requirements a supported passage answers."""
    goal = "为什么不阻塞、主要代价是什么"

    class Body:
        text = MECHANISM

    def completion(**_kwargs):
        return json.dumps({"verdicts": [{"claim_id": "c0", "verdict": "supported",
                                         "reason": "states the mechanism",
                                         "covers": [0, 99, "x"]}]})

    from src.web.research_claims import Claim

    quote = "代价是旧版本必须清理"
    claim = Claim(goal_id=goal, claim="c", source_id="S1", span_start=MECHANISM.find(quote),
                  span_end=MECHANISM.find(quote) + len(quote), quote=quote)
    verdicts = verify_claims(claims=[claim], goals={goal: ("快照",)}, label_to_id={goal: goal},
                             bodies={"S1": Body()}, adopted=None, completion=completion,
                             timeout=5.0)
    assert verdicts[0].verdict == "supported"
    assert verdicts[0].covers == (0,)          # out-of-range and non-integer entries dropped


def test_verifier_never_claims_coverage_for_an_unsupported_verdict():
    goal = "为什么不阻塞、主要代价是什么"

    class Body:
        text = MECHANISM

    def completion(**_kwargs):
        return json.dumps({"verdicts": [{"claim_id": "c0", "verdict": "insufficient",
                                         "reason": "not stated", "covers": [0, 1]}]})

    from src.web.research_claims import Claim

    quote = "代价是旧版本必须清理"
    claim = Claim(goal_id=goal, claim="c", source_id="S1", span_start=MECHANISM.find(quote),
                  span_end=MECHANISM.find(quote) + len(quote), quote=quote)
    verdicts = verify_claims(claims=[claim], goals={goal: ("快照",)}, label_to_id={goal: goal},
                             bodies={"S1": Body()}, adopted=None, completion=completion,
                             timeout=5.0)
    assert verdicts[0].verdict == "insufficient"
    assert verdicts[0].covers == ()
