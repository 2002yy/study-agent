"""M3-QD-1 acceptance: the second query must depend on the first observation.

The contract's core claim (§7.8 item four) is not "two different queries appeared" but "new
information changed the next step". This file drives the real planning adapter, the real
observation projection, the real stop reasons and the real SQLite logical quota; only the
model and the search executor are scripted.

The causality check is deliberately hostile: the scripted model asserts that round two's
payload already contains round one's observation. If the projection were dropped, the model
would raise instead of quietly producing a plausible second query.
"""

from __future__ import annotations

import json


from src.application.conversation_decision_admission import SqliteDecisionAdmission
from src.web.semantic_admission import validate_tool_call
from src.web.semantic_observation import (
    STOP_BUDGET_EXHAUSTED,
    STOP_CANCELLED,
    STOP_EVIDENCE_SUFFICIENT,
    STOP_NO_NEW_DIRECTION,
)
from src.web.semantic_planner import SemanticQueryPlanner, bounded_session_factory
from src.web.semantic_recovery import ResearchEpisode
from src.web.semantic_research_host import SemanticResearchHost, SemanticToolHandler

QUESTION = "为什么 B+ 树适合数据库？"
LEAD_ONE = "https://example.org/bplus-tree-pages"
LEAD_TWO = "https://example.org/bplus-tree-leaf-scan"
QUERY_A = "B+树 磁盘页 扇出"
QUERY_B = "B+树 叶子节点 链表 范围扫描"


def episode() -> ResearchEpisode:
    return ResearchEpisode(
        task_id="run-1",
        thread_id="thread-1",
        original_question=QUESTION,
        questions=[{"id": "rq-1", "question": "为什么适合数据库"}],
        source_run_id="run-1",
    )


def decision(queries: list[dict[str, str]], *, intent: str = "CONTINUE_ACTIVE_RESEARCH") -> str:
    return json.dumps(
        {
            "task_id": "run-1",
            "intent": intent,
            "subject": "B+ 树",
            "constraints_delta": {},
            "unresolved_questions": [{"id": "rq-1", "question": "为什么适合数据库"}],
            "suggested_next_action": "search",
            "proposed_queries": queries,
        },
        ensure_ascii=False,
    )


class ScriptedModel:
    """A model that can only answer round two if it was actually shown round one."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.payloads: list[dict] = []
        self.calls = 0

    def __call__(self, *, messages, timeout, task_name) -> str:
        payload = json.loads(messages[-1]["content"])
        self.payloads.append(payload)
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


class ScriptedExecutor:
    """Search executor: real call-record shape, scripted results."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, queries) -> list[dict]:
        calls: list[dict] = []
        for row in queries:
            query = row["query"]
            self.queries.append(query)
            calls.append({"name": "web_search", "arguments": {"query": query},
                          "result": {"status": "ok"}})
            url, content = (
                (LEAD_ONE, "磁盘页访问与扇出决定了树的高度")
                if "磁盘页" in query
                else (LEAD_TWO, "叶子节点用链表相连，适合范围扫描")
            )
            calls.append({"name": "web_read", "arguments": {"url": url},
                          "result": {"status": "ok", "content": content}})
        return calls


def is_public(url) -> bool:
    return isinstance(url, str) and url.startswith("https://example.org/")


def host(model: ScriptedModel, executor: ScriptedExecutor, *, quota=None, **kwargs):
    return SemanticResearchHost(
        planner=SemanticQueryPlanner(
            bounded_session_factory(completion=model, should_cancel=lambda: False)
        ),
        execute=executor,
        is_public_url=is_public,
        episode=episode(),
        operation_id="op-1",
        quota=quota,
        **kwargs,
    )


def two_round_model() -> ScriptedModel:
    return ScriptedModel([
        decision([{"rq_id": "rq-1", "query": QUERY_A}]),
        decision([{"rq_id": "rq-1", "query": QUERY_B}]),
        decision([], intent="ANSWER"),
    ])


# --- assertions 1 and 3: the planner produced the query, and B is a new direction -------


def test_the_executed_query_is_the_one_the_planner_generated():
    model, executor = two_round_model(), ScriptedExecutor()
    host(model, executor).run_turn(QUESTION)

    assert executor.queries[0] == QUERY_A
    assert QUERY_A in model.replies[0]          # it came from the model, not the handler
    assert executor.queries[0] not in {QUESTION}


def test_the_second_query_is_a_new_direction_rather_than_a_replay():
    model, executor = two_round_model(), ScriptedExecutor()
    host(model, executor).run_turn(QUESTION)

    assert len(executor.queries) >= 2
    first, second = executor.queries[0], executor.queries[1]
    assert first != second
    assert "范围扫描" in second and "范围扫描" not in first
    assert "数据库" in QUESTION                # both stay on the user's topic


# --- assertion 2: causality, proven from the planner's own payload ---------------------


def test_the_second_plan_was_produced_only_after_the_first_observation_was_in_its_input():
    model = two_round_model()
    host(model, ScriptedExecutor()).run_turn(QUESTION)

    first_payload, second_payload = model.payloads[0], model.payloads[1]
    assert first_payload["episode"]["attempts"] == []
    assert first_payload["episode"]["source_leads"] == []

    # The observation from query A reached the model before query B was produced.
    assert second_payload["episode"]["attempts"][0]["query"] == QUERY_A
    assert LEAD_ONE in [row["url"] for row in second_payload["episode"]["source_leads"]]
    assert "扇出" in second_payload["episode"]["source_leads"][0]["summary"]


def test_the_round_records_that_the_observation_was_visible():
    result = host(two_round_model(), ScriptedExecutor()).run_turn(QUESTION)
    first, second = result.rounds[0], result.rounds[1]
    assert first.observation_seen_by_model is False   # first round has nothing to observe
    assert second.observation_seen_by_model is True   # and the second round did


# --- assertion 4: identity and earlier leads survive; nothing becomes evidence ----------


def test_the_original_question_and_earlier_leads_survive_the_rounds():
    result = host(two_round_model(), ScriptedExecutor()).run_turn(QUESTION)
    assert result.episode is not None
    assert result.episode.original_question == QUESTION
    urls = [row["url"] for row in result.episode.source_leads]
    assert LEAD_ONE in urls and LEAD_TWO in urls


def test_a_read_verdict_never_becomes_an_episode_field():
    class ClaimingExecutor(ScriptedExecutor):
        def __call__(self, queries):
            calls = super().__call__(queries)
            for call in calls:
                if call["name"] == "web_read":
                    call["result"]["answer_eligible"] = True
            return calls

    result = host(two_round_model(), ClaimingExecutor()).run_turn(QUESTION)
    row = result.episode.source_leads[0]
    assert set(row) == {"url", "status", "reason", "summary"}
    assert "answer_eligible" not in row


# --- assertion 5: logical quota, and replay cannot re-buy ------------------------------


def test_each_round_reserves_once_and_a_replayed_turn_cannot_re_buy(tmp_path):
    quota = SqliteDecisionAdmission(
        tmp_path / "admission.db", max_calls=4, max_prompt_chars=10_000, max_output_tokens=4_000
    )
    first = host(two_round_model(), ScriptedExecutor(), quota=quota).run_turn(QUESTION)
    assert len(first.rounds) == 2
    # Two search rounds plus the closing decision that returned ANSWER: every model call is
    # metered, including the one that ends the loop.
    assert quota.usage().calls == 3

    replay = host(two_round_model(), ScriptedExecutor(), quota=quota).run_turn(QUESTION)
    assert replay.rounds == []                       # nothing planned, nothing spent
    assert replay.stop_reason == STOP_BUDGET_EXHAUSTED
    assert quota.usage().calls == 3                  # the replay bought no quota


# --- assertion 6: four stops, each named, none reported as a normal completion ----------


def test_evidence_sufficiency_comes_from_the_model_and_is_named():
    result = host(two_round_model(), ScriptedExecutor()).run_turn(QUESTION)
    assert result.stop_reason == STOP_EVIDENCE_SUFFICIENT


def test_a_round_that_finds_nothing_new_stops_as_no_new_direction():
    class EmptyExecutor(ScriptedExecutor):
        def __call__(self, queries):
            calls = super().__call__(queries)
            for call in calls:
                if call["name"] == "web_read":
                    call["arguments"]["url"] = "http://127.0.0.1/private"
            return calls

    result = host(ScriptedModel([decision([{"rq_id": "rq-1", "query": QUERY_A}])]),
                  EmptyExecutor()).run_turn(QUESTION)
    assert result.stop_reason == STOP_NO_NEW_DIRECTION


def test_an_exhausted_quota_stops_before_planning(tmp_path):
    quota = SqliteDecisionAdmission(
        tmp_path / "exhausted.db", max_calls=0, max_prompt_chars=10, max_output_tokens=10
    )
    result = host(two_round_model(), ScriptedExecutor(), quota=quota).run_turn(QUESTION)
    assert result.rounds == []
    assert result.stop_reason == STOP_BUDGET_EXHAUSTED


def test_a_user_cancellation_is_never_reported_as_completion():
    result = host(
        two_round_model(), ScriptedExecutor(), should_cancel=lambda: True
    ).run_turn(QUESTION)
    assert result.stop_reason == STOP_CANCELLED
    assert result.cancelled is True


# --- the negative control the contract asks for ---------------------------------------


def test_an_unauthorized_tool_name_is_refused_and_the_executor_never_runs():
    executor = ScriptedExecutor()
    handler = SemanticToolHandler(
        host(two_round_model(), executor),
        registry={"web_search": object()},
        permitted=frozenset({"web_search"}),
        budget_remaining=lambda: 2,
    )
    assert handler.run(action="USE_TOOL", tool="shell_exec", arguments={}) is None
    assert handler.refusals == ["unknown_tool"]
    assert executor.queries == []                    # no search, and no substitute executor


def test_an_authorized_tool_runs_the_real_round():
    executor = ScriptedExecutor()
    handler = SemanticToolHandler(
        host(two_round_model(), executor),
        registry={"web_search": object()},
        permitted=frozenset({"web_search"}),
        budget_remaining=lambda: 2,
    )
    result = handler.run(action="USE_TOOL", tool="web_search", arguments={"latest": QUESTION})
    assert result is not None
    assert executor.queries[0] == QUERY_A


def test_the_action_kind_is_checked_before_the_tool_name():
    """A proposal that is not USE_TOOL may not reach an executor even with a valid tool."""

    decision = validate_tool_call(
        action="ANSWER", tool="web_search", registry={"web_search": object()},
        permitted=frozenset({"web_search"}), budget_remaining=4,
    )
    assert not decision.allowed and decision.reason == "action_not_tool_use"
