"""M3-QA acceptance: the middle planning adapter.

Each test maps to a clause of docs/CL_M3_CAPABILITY_CONTRACT.md. The negative controls are
the point: a planner that produces plausible queries but cannot prove the guarantees is not
acceptance.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import pytest

from src.web.research_recovery import recover_public_research
from src.web.semantic_planner import (
    PlanningIdentity,
    SemanticQueryPlanner,
    bounded_session_factory,
    plan_queries,
)
from src.web.semantic_recovery import ResearchEpisode, ResearchSemanticSession


def make_episode(
    *,
    questions: list[dict[str, str]] | None = None,
    attempts: list[dict[str, str]] | None = None,
    leads: list[dict[str, str]] | None = None,
    original: str = "二分查找的边界条件怎么确定",
) -> ResearchEpisode:
    return ResearchEpisode(
        task_id="run-1",
        thread_id="thread-1",
        original_question=original,
        questions=questions or [{"id": "rq-1", "question": "边界条件怎么确定"}],
        attempts=attempts or [],
        source_leads=leads or [],
    )


def decision_payload(
    *,
    intent: str = "CONTINUE_ACTIVE_RESEARCH",
    questions: list[dict[str, str]] | None = None,
    queries: list[dict[str, str]] | None = None,
    constraints: dict[str, str] | None = None,
) -> dict:
    return {
        "task_id": "run-1",
        "intent": intent,
        "subject": "二分查找边界",
        "constraints_delta": constraints or {},
        "unresolved_questions": questions or [{"id": "rq-1", "question": "边界条件怎么确定"}],
        "suggested_next_action": "search official docs",
        "proposed_queries": queries
        if queries is not None
        else [{"rq_id": "rq-1", "query": "二分查找 边界 下界不变式"}],
    }


class Recorder:
    """Fake completion that returns a fixed decision and records the calls."""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or decision_payload()
        self.calls: list[str] = []

    def __call__(self, *, messages, timeout, task_name) -> str:
        self.calls.append(task_name)
        return json.dumps(self.payload, ensure_ascii=False)


def planner_for(recorder: Recorder, *, history_allowed: bool = False) -> SemanticQueryPlanner:
    return SemanticQueryPlanner(
        bounded_session_factory(
            completion=recorder,
            should_cancel=lambda: False,
            history_allowed=history_allowed,
        )
    )


def now() -> float:
    return time.monotonic() + 5.0


# --- Q-1/Q-2: the model produces the queries ----------------------------------------


def test_queries_come_from_the_planner_including_concepts_the_user_never_said():
    recorder = Recorder(
        decision_payload(queries=[{"rq_id": "rq-1", "query": "二分查找 下界不变式"}])
    )
    round_result = planner_for(recorder).plan(
        make_episode(), "讲讲二分查找", identity=PlanningIdentity("op-1", 0), deadline=now()
    )
    assert [row["query"] for row in round_result.queries] == ["二分查找 下界不变式"]
    # The concept is not in the user's own words; it came from the planner.
    assert "下界不变式" not in "讲讲二分查找"
    assert recorder.calls == ["research_turn_interpretation"]


def test_history_is_only_forwarded_when_the_policy_allows_it():
    seen: list[str] = []

    def completion(*, messages, timeout, task_name) -> str:
        seen.append(messages[1]["content"])
        return json.dumps(decision_payload(), ensure_ascii=False)

    planner = SemanticQueryPlanner(
        bounded_session_factory(
            completion=completion, should_cancel=lambda: False, history_allowed=False
        )
    )
    planner.plan(
        make_episode(),
        "继续",
        identity=PlanningIdentity("op-1", 0),
        deadline=now(),
        history="用户之前说过：这是我的私人备注内容",
    )
    assert "私人备注内容" not in seen[0]


# --- §7.4: one fresh session per round -----------------------------------------------


def test_each_round_gets_a_fresh_session_so_replanning_is_possible():
    recorder = Recorder()
    identities: list[str] = []

    def factory(identity, deadline):
        identities.append(identity.key)
        return ResearchSemanticSession(
            recorder, deadline=deadline, should_cancel=lambda: False
        )

    planner = SemanticQueryPlanner(factory)
    first = planner.plan(
        make_episode(), "讲讲二分查找", identity=PlanningIdentity("op-1", 0), deadline=now()
    )
    second = planner.plan(
        first.episode,
        "换个方向",
        identity=PlanningIdentity("op-1", 1),
        deadline=now(),
    )
    assert identities == ["op-1#r0#research_turn_interpretation", "op-1#r1#research_turn_interpretation"]
    assert first.identity.key != second.identity.key


def test_a_single_session_still_refuses_a_second_interpretation():
    """The reason a fresh session per round is mandatory, stated as a test."""

    recorder = Recorder()
    session = ResearchSemanticSession(
        recorder, deadline=now(), should_cancel=lambda: False
    )
    session.interpret(make_episode(), "讲讲二分查找")
    with pytest.raises(ValueError, match="semantic_call_limit"):
        session.interpret(make_episode(), "再讲讲")


def test_identity_is_stable_and_rejects_nonsense():
    identity = PlanningIdentity("op-1", 2)
    assert identity.key == PlanningIdentity("op-1", 2).key
    assert identity.key != PlanningIdentity("op-1", 3).key
    with pytest.raises(ValueError):
        PlanningIdentity("", 0)
    with pytest.raises(ValueError):
        PlanningIdentity("op-1", -1)


# --- §7.6: the original RQ cannot be removed ----------------------------------------


def test_removing_an_original_question_is_rejected():
    episode = make_episode(
        questions=[
            {"id": "rq-1", "question": "边界条件怎么确定"},
            {"id": "rq-2", "question": "复杂度是多少"},
        ]
    )
    recorder = Recorder(
        decision_payload(
            questions=[{"id": "rq-2", "question": "复杂度是多少"}],
            queries=[{"rq_id": "rq-2", "query": "二分查找 复杂度"}],
        )
    )
    with pytest.raises(ValueError, match="original_rq_removed"):
        planner_for(recorder).plan(
            episode, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
        )


def test_the_original_wording_wins_over_a_model_rephrasing():
    episode = make_episode(questions=[{"id": "rq-1", "question": "边界条件怎么确定"}])
    recorder = Recorder(
        decision_payload(
            questions=[{"id": "rq-1", "question": "边界条件与不变式的关系"}],
            queries=[{"rq_id": "rq-1", "query": "二分查找 不变式"}],
        )
    )
    round_result = planner_for(recorder).plan(
        episode, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert round_result.episode is not None
    assert round_result.episode.questions == [{"id": "rq-1", "question": "边界条件怎么确定"}]


def test_the_merged_episode_matches_the_frozen_legacy_transformation():
    """Equivalence with the block CL-M3 replaces (``persistent_web_agent`` 507-514).

    The expected value is written out literally rather than recomputed with the same
    expression, so this is an oracle and not a tautology: the original RQs keep their
    wording, the model may append new RQs, and ``constraints_delta`` merges over the
    episode's constraints without dropping what was already there.
    """

    episode = make_episode(
        questions=[
            {"id": "rq-1", "question": "边界条件怎么确定"},
            {"id": "rq-2", "question": "复杂度是多少"},
        ]
    )
    episode = replace(episode, constraints={"source_preference": "official"})
    recorder = Recorder(
        decision_payload(
            questions=[
                {"id": "rq-1", "question": "边界条件与不变式的关系"},
                {"id": "rq-2", "question": "复杂度是多少"},
                {"id": "rq-3", "question": "循环终止怎么证明"},
            ],
            queries=[{"rq_id": "rq-3", "query": "二分查找 循环终止 证明"}],
            constraints={"focus": "官方文档"},
        )
    )
    round_result = planner_for(recorder).plan(
        episode, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert round_result.episode is not None
    assert round_result.episode.questions == [
        {"id": "rq-1", "question": "边界条件怎么确定"},
        {"id": "rq-2", "question": "复杂度是多少"},
        {"id": "rq-3", "question": "循环终止怎么证明"},
    ]
    assert round_result.episode.constraints == {
        "source_preference": "official",
        "focus": "官方文档",
    }


# --- Q-3 / §7.5: observation may be dropped, and must not be lied about -------------


def _episode_with_full_observation() -> ResearchEpisode:
    """Fill every field to the cap ``ResearchEpisode.parse`` itself allows.

    The sizes matter: ``episode_context`` only degrades when the serialised payload exceeds
    ``CONTEXT_CAP``, so an episode that merely looks large proves nothing. These are the
    real ceilings (``original_question`` 4096, ``attempts.query`` 500 / ``outcome`` 100,
    ``source_lead`` ``reason``/``summary`` 300, five leads) paired with a 4096-char
    ``latest_message``; together they overshoot 16000 while leaving the post-degradation
    payload comfortably under it.
    """

    attempts = [{"query": "q" * 500, "outcome": "o" * 100} for _ in range(8)]
    leads = [
        {"url": "https://example.com/" + "a" * 200 + f"/{index}", "status": "o" * 100,
         "reason": "r" * 300, "summary": "s" * 300}
        for index in range(5)
    ]
    return make_episode(attempts=attempts, leads=leads, original="x" * 4096)


def test_dropped_observations_cannot_be_claimed_as_replanning_input():
    recorder = Recorder()
    round_result = planner_for(recorder).plan(
        _episode_with_full_observation(),
        "y" * 4096,
        identity=PlanningIdentity("op-1", 1),
        deadline=now(),
    )
    # §7.5: the observations were written to the episode but did not reach the model.
    assert "attempts" in round_result.omitted
    assert "source_leads" in round_result.omitted
    assert round_result.observation_available is False
    with pytest.raises(ValueError, match="observation_not_visible"):
        round_result.assert_may_claim_observation_driven()


def test_visible_observations_allow_the_claim_only_after_the_first_round():
    episode = make_episode(attempts=[{"query": "二分查找 边界", "outcome": "insufficient"}])
    round_result = planner_for(Recorder()).plan(
        episode, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert round_result.observation_available is True
    round_result.assert_may_claim_observation_driven()

    first_round = planner_for(Recorder()).plan(
        episode, "讲讲二分查找", identity=PlanningIdentity("op-1", 0), deadline=now()
    )
    with pytest.raises(ValueError, match="observation_claim_on_first_round"):
        first_round.assert_may_claim_observation_driven()


def test_an_episode_without_observations_cannot_claim_observation_driven():
    """Nothing was dropped here - there was simply nothing to observe.

    §7.5 has two failure modes, and only one of them shows up in ``omitted``. A planner that
    keys the claim off ``omitted`` alone would wrongly permit it on a first-round episode
    that happens to carry no attempts yet.
    """

    round_result = planner_for(Recorder()).plan(
        make_episode(), "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert round_result.omitted == ("full_history", "historical_source_bodies")
    assert round_result.observation_available is False
    with pytest.raises(ValueError, match="observation_not_visible"):
        round_result.assert_may_claim_observation_driven()


# --- Q-8: equivalence under a fixed model response ----------------------------------


def test_same_inputs_and_fixed_model_output_produce_the_same_plan():
    inputs = make_episode(
        questions=[{"id": "rq-1", "question": "边界条件怎么确定"},
                   {"id": "rq-2", "question": "复杂度是多少"}]
    )
    payload = decision_payload(
        questions=[{"id": "rq-1", "question": "边界条件怎么确定"},
                   {"id": "rq-2", "question": "复杂度是多少"}],
        queries=[{"rq_id": "rq-1", "query": "二分查找 边界"},
                 {"rq_id": "rq-2", "query": "二分查找 复杂度"}],
    )
    first = planner_for(Recorder(payload)).plan(
        inputs, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    second = planner_for(Recorder(payload)).plan(
        inputs, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert first.queries == second.queries
    assert first.episode is not None and second.episode is not None
    assert first.episode.to_dict() == second.episode.to_dict()


# --- §9.5: the deadline is injected, not read from a global window -------------------


def test_an_expired_deadline_is_refused():
    with pytest.raises(TimeoutError):
        planner_for(Recorder()).plan(
            make_episode(),
            "继续",
            identity=PlanningIdentity("op-1", 1),
            deadline=time.monotonic() - 1.0,
        )


def test_the_caller_may_hand_this_phase_its_own_slice_of_the_budget():
    """Reserves P-2: the adapter never assumes the whole turn's window."""

    recorder = Recorder()
    planner = planner_for(recorder)
    round_result = planner.plan(
        make_episode(),
        "继续",
        identity=PlanningIdentity("op-1", 1),
        deadline=time.monotonic() + 60.0,
    )
    assert round_result.queries


# --- intents that carry no plan ------------------------------------------------------


def test_abstain_passes_the_episode_through_without_a_question_merge():
    recorder = Recorder(
        decision_payload(
            intent="ABSTAIN",
            questions=[{"id": "rq-other", "question": "无关问题"}],
            queries=[],
        )
    )
    episode = make_episode()
    round_result = planner_for(recorder).plan(
        episode, "继续", identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert round_result.queries == ()
    assert round_result.episode is episode
    assert round_result.new_topic is False


def test_a_new_topic_requires_the_host_to_open_a_fresh_episode():
    recorder = Recorder(
        decision_payload(
            intent="NEW_RESEARCH",
            questions=[{"id": "rq-new", "question": "另一个话题"}],
            queries=[{"rq_id": "rq-new", "query": "另一个话题 资料"}],
        )
    )
    round_result = planner_for(recorder).plan(
        make_episode(), "换个话题", identity=PlanningIdentity("op-1", 0), deadline=now()
    )
    assert round_result.new_topic is True
    assert round_result.episode is None


# --- the flat view the outer loop consumes -------------------------------------------


def test_the_flat_view_is_json_safe_and_carries_no_authority():
    view = plan_queries(
        planner_for(Recorder()),
        make_episode(),
        "继续",
        identity=PlanningIdentity("op-1", 1),
        deadline=now(),
    )
    json.dumps(view, ensure_ascii=False)
    assert set(view) == {
        "identity", "intent", "subject", "queries", "new_topic", "omitted",
        "observation_available", "episode",
    }
    assert view["identity"] == "op-1#r1#research_turn_interpretation"


# --- QA acceptance: the executor issues the planner's query ---------------------------


class RecordingGateway:
    """Executor gateway that records the queries it is actually asked to search."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search_exact(self, query: str, **_kwargs) -> dict:
        self.queries.append(query)
        return {"status": "ok", "results": []}

    def read(self, url: str, **_kwargs) -> dict:
        return {"ok": False, "url": url, "error": "not needed"}


def test_the_executor_searches_the_planner_generated_concept():
    """QA: "the executor really uses the query", not just "the model produced a query".

    The planner returns a plan and nothing else; this drives that plan through the real
    ``recover_public_research`` executor and reads back what it actually searched. The
    concept under test never appears in the user's turn, so the assertion cannot be
    satisfied by echoing the input back.
    """

    user_turn = "二分查找怎么写"
    concept = "下界不变式"
    assert concept not in user_turn

    recorder = Recorder(
        decision_payload(
            queries=[{"rq_id": "rq-1", "query": f"二分查找 {concept} 循环终止"}]
        )
    )
    round_result = planner_for(recorder).plan(
        make_episode(), user_turn, identity=PlanningIdentity("op-1", 1), deadline=now()
    )
    assert concept in round_result.queries[0]["query"]

    gateway = RecordingGateway()
    recover_public_research(gateway, user_turn, query_plan=[dict(row) for row in round_result.queries])

    assert gateway.queries, "the executor never searched"
    assert any(concept in query for query in gateway.queries), gateway.queries
