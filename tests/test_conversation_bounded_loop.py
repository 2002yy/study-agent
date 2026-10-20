"""Opt-in loop ordering and negative controls; no live model quality claim."""

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json

import pytest

from src.application.conversation_action_dispatch import (
    ActionBudget,
    ActionEvent,
    SteeringObservation,
)
from src.application.conversation_bounded_loop import (
    LoopLimits,
    LoopStopped,
    run_conversation_loop,
)
from src.application.conversation_decision import (
    ActiveResearch,
    ConversationAction,
    DecisionContext,
)
from src.application.conversation_decision_runner import DecisionBudget, DecisionResult


def scenario(
    actions=("use_tool", "answer"),
    *,
    tools=2,
    limits=None,
    model=None,
    handler=None,
    decision_budget=None,
    action_budget=None,
    active_research=None,
    supports_queue=False,
):
    root = DecisionContext(
        "loop-1",
        "先分析再计算",
        available_tools=("compute",),
        remaining_tool_calls=tools,
        active_research=active_research,
        supports_queue=supports_queue,
    )
    state, calls = [root], []
    choices = iter(actions)

    async def transport(request):
        calls.append("model")
        if model:
            return await model(request)
        data = json.loads(request.messages[1][1])
        action = next(choices)
        tool = "compute" if action in {"use_tool", "answer_then_research"} else None
        return json.dumps(
            {
                "schema": "conversation-decision-v1",
                "request_id": data["request_id"],
                "action": action,
                "relation": "supplement" if action == "steer" else "new_topic",
                "reason": "选择下一步",
                "focus": "计算",
                "tool": tool,
                "target_run_id": data["active_research"]["run_id"]
                if action in {"steer", "queue"}
                else None,
                "target_revision": data["active_research"]["revision"]
                if action in {"steer", "queue"}
                else None,
                "active_run_disposition": "keep" if data["active_research"] else "none",
            }
        )

    async def action(invocation):
        calls.append(invocation.stage.value)
        if handler:
            return await handler(invocation)
        if invocation.stage == ConversationAction.USE_TOOL:
            state[0] = replace(
                state[0], remaining_tool_calls=state[0].remaining_tool_calls - 1
            )
            return str(2 + 3)
        return (
            "初步判断"
            if invocation.proposal.action == ConversationAction.ANSWER_THEN_RESEARCH
            else "结果为5"
        )

    stream = run_conversation_loop(
        root,
        current_context=lambda: state[0],
        transport=transport,
        decision_budget=decision_budget or DecisionBudget(8, 1000000, 6400),
        action_budget=action_budget or ActionBudget(8, tools),
        handlers={kind: action for kind in ConversationAction},
        limits=limits or LoopLimits(),
    )
    return root, state, calls, stream


async def collect(stream):
    return [event async for event in stream]


def trail_choice(request, action):
    data = json.loads(request.messages[1][1])
    return json.dumps(
        {
            "schema": "conversation-decision-v1",
            "request_id": data["request_id"],
            "action": action,
            "relation": "continuation",
            "reason": "继续本轮分析",
            "focus": "计算",
            "tool": "compute"
            if action in {"use_tool", "answer_then_research"}
            else None,
            "target_run_id": None,
            "target_revision": None,
            "active_run_disposition": "keep" if data["active_research"] else "none",
        }
    )


def test_all_tools_and_already_shown_reply_reach_later_model_in_order():
    async def run():
        requests = []
        tool_values = iter((2 + 3, 2 * 3))

        async def model(request):
            index = len(requests)
            requests.append(request)
            if index:
                body = json.loads(request.messages[-1][1])
                assert body["schema"] == "conversation-observation-trail-v1"
                assert [item["content"] for item in body["entries"]] == [
                    "先求和再求积",
                    "5",
                ] + (["6"] if index == 2 else [])
                assert body["entries"][0]["kind"] == "assistant_preliminary"
                assert all(
                    item["verification"] == "unverified" for item in body["entries"]
                )
                original = json.loads(request.messages[1][1])
                assert (
                    original["history"] == []
                    and original["evidence_summary"] == root.evidence_summary
                )
            return trail_choice(
                request, ("answer_then_research", "use_tool", "answer")[index]
            )

        async def handler(invocation):
            if invocation.stage == ConversationAction.USE_TOOL:
                state[0] = replace(
                    state[0], remaining_tool_calls=state[0].remaining_tool_calls - 1
                )
                return str(next(tool_values))
            return (
                "先求和再求积"
                if invocation.proposal.action == ConversationAction.ANSWER_THEN_RESEARCH
                else "和为5，积为6"
            )

        root, state, calls, stream = scenario(tools=2, model=model, handler=handler)
        async with aclosing(stream):
            await anext(stream)
            assert (await anext(stream)).observation == "先求和再求积"
            assert calls == ["model", "answer"]
            rest = await collect(stream)
        assert rest[-1] == LoopStopped("answered", 3, 4)
        assert rest[-2].observation == "和为5，积为6"
        assert calls == [
            "model",
            "answer",
            "use_tool",
            "model",
            "use_tool",
            "model",
            "answer",
        ]

    asyncio.run(run())


@pytest.mark.parametrize("overflow_stage", ["tool", "preliminary"])
def test_observation_capacity_stops_future_calls_without_hiding_completed_output(
    overflow_stage,
):
    async def run():
        async def handler(invocation):
            if invocation.stage == ConversationAction.USE_TOOL:
                state[0] = replace(
                    state[0], remaining_tool_calls=state[0].remaining_tool_calls - 1
                )
            return "x" * 8000

        choices = (
            "use_tool",
            "use_tool" if overflow_stage == "tool" else "answer_then_research",
        )
        from src.application.conversation_loop_session import ConversationLoopSession

        root, state, calls, stream = scenario(choices, tools=2, handler=handler)
        session = ConversationLoopSession(root.request_id, stream)
        async with aclosing(session.events()) as events_stream:
            events = await collect(events_stream)
        assert events[-1] == LoopStopped("observation_limit", 2, 2)
        assert session.receipt.status == "stopped"
        assert session.receipt.stop_reason == "observation_limit"
        assert session.receipt.observations == 2 and not session.receipt.outcome_unknown
        completed = [item for item in events if isinstance(item, ActionEvent)]
        assert len(completed) == 2 and all(
            len(item.observation) == 8000 for item in completed
        )
        assert calls.count("model") == 2
        # Overflow after a preliminary answer must not start its reserved tool stage.
        assert calls.count("use_tool") == (2 if overflow_stage == "tool" else 1)

    asyncio.run(run())


def test_cumulative_prompt_budget_is_checked_before_third_model_call():
    async def run():
        sizes = []

        class ProbeAdmission:
            def reserve(self, request_id, prompt_chars, output_tokens):
                sizes.append(prompt_chars)
                return "reserved"

        # Establish public admission sizes, then make the real ledger one
        # character short of admitting the third cumulative prompt.
        _, _, _, probe = scenario(
            ("use_tool", "use_tool", "answer"),
            tools=2,
            decision_budget=ProbeAdmission(),
        )
        assert (await collect(probe))[-1].reason == "answered"
        assert len(sizes) == 3 and sizes[2] > sizes[1]
        budget = DecisionBudget(3, sum(sizes) - 1, 2400)
        _, _, calls, stream = scenario(
            ("use_tool", "use_tool", "answer"), tools=2, decision_budget=budget
        )
        events = await collect(stream)
        assert events[-1] == LoopStopped(
            "decision_failed", 3, 2, False, "budget_exhausted"
        )
        assert calls == ["model", "use_tool", "model", "use_tool"]

    asyncio.run(run())


def test_eight_steps_retain_all_prior_preliminary_answers_and_tools():
    async def run():
        observed_counts = []

        async def model(request):
            if len(request.messages) == 4:
                observed_counts.append(
                    len(json.loads(request.messages[-1][1])["entries"])
                )
            return trail_choice(request, "answer_then_research")

        _, _, calls, stream = scenario(
            tools=8, model=model, limits=LoopLimits(max_decisions=8)
        )
        events = await collect(stream)
        assert observed_counts == [2, 4, 6, 8, 10, 12, 14]
        assert events[-1] == LoopStopped("decision_limit", 8, 16)
        assert calls.count("model") == 8 and calls.count("use_tool") == 8

    asyncio.run(run())


@pytest.mark.parametrize(
    "change", ["own_revision", "concurrent_revision", "new_topic", "before_handler"]
)
def test_tool_then_steer_preserves_identity_but_requires_exact_revision_receipt(change):
    async def run():
        active = ActiveResearch("run-1", 1, "原研究", True)

        async def handler(invocation):
            if invocation.stage == ConversationAction.USE_TOOL:
                state[0] = replace(
                    state[0], remaining_tool_calls=state[0].remaining_tool_calls - 1
                )
                return "工具结果"
            committed = replace(active, revision=2, question="转向后的研究")
            state[0] = replace(state[0], active_research=committed)
            if change == "concurrent_revision":
                state[0] = replace(
                    state[0], active_research=replace(committed, revision=3)
                )
            if change == "new_topic":
                state[0] = replace(state[0], user_message="另一个问题")
            return SteeringObservation("已接收转向", committed)

        _, state, calls, stream = scenario(
            ("use_tool", "steer"), active_research=active, handler=handler
        )
        first = [await anext(stream) for _ in range(3)]
        assert (
            isinstance(first[-1], DecisionResult)
            and first[-1].proposal.action == ConversationAction.STEER
        )
        if change == "before_handler":
            state[0] = replace(state[0], active_research=replace(active, revision=2))
        rest = await collect(stream)
        if change == "own_revision":
            assert rest[-1] == LoopStopped("steering_observed", 2, 2)
            assert rest[0].request_id == first[-1].proposal.request_id
        else:
            assert rest[-1] == LoopStopped(
                "action_failed", 2, 1, False, "stale_context"
            )
        assert calls.count("steer") == (0 if change == "before_handler" else 1)

    asyncio.run(run())


def test_tool_then_queue_keeps_projected_identity_and_stops():
    _, _, calls, stream = scenario(
        ("use_tool", "queue"),
        active_research=ActiveResearch("run-1", 1, "原研究", True),
        supports_queue=True,
    )
    events = asyncio.run(collect(stream))
    assert events[-1] == LoopStopped("queue_observed", 2, 2)
    assert calls == ["model", "use_tool", "model", "queue"]


def test_answer_then_research_streams_before_tool_and_next_answer():
    async def run():
        _, _, calls, stream = scenario(("answer_then_research", "answer"))
        async with aclosing(stream):
            assert isinstance(await anext(stream), DecisionResult)
            assert calls == ["model"]
            event = await anext(stream)
            assert isinstance(event, ActionEvent) and event.observation == "初步判断"
            assert calls == ["model", "answer"]
            rest = await collect(stream)
        assert calls == ["model", "answer", "use_tool", "model", "answer"]
        assert rest[-1] == LoopStopped("answered", 2, 3)
        assert sum(isinstance(item, LoopStopped) for item in rest) == 1

    asyncio.run(run())


def test_three_tools_can_be_followed_by_answer_with_distinct_action_identities():
    async def run():
        _, state, calls, stream = scenario(
            ("use_tool", "use_tool", "use_tool", "answer"), tools=3
        )
        events = await collect(stream)
        decisions = [item for item in events if isinstance(item, DecisionResult)]
        assert len({item.proposal.request_id for item in decisions}) == 4
        assert state[0].remaining_tool_calls == 0
        assert events[-1] == LoopStopped("answered", 4, 4)
        assert calls.count("model") == 4 and calls.count("use_tool") == 3

    asyncio.run(run())


@pytest.mark.parametrize("max_decisions", [1, 2, 3])
def test_repeated_tool_choices_stop_at_step_cap_without_next_model(max_decisions):
    async def run():
        _, _, calls, stream = scenario(
            ("use_tool",) * 8, tools=8, limits=LoopLimits(max_decisions=max_decisions)
        )
        events = await collect(stream)
        assert events[-1] == LoopStopped("decision_limit", max_decisions, max_decisions)
        assert calls.count("model") == max_decisions

    asyncio.run(run())


@pytest.mark.parametrize(
    "action,reason", [("answer", "answered"), ("clarify", "clarification_required")]
)
def test_non_tool_action_is_terminal(action, reason):
    _, _, calls, stream = scenario((action,))
    events = asyncio.run(collect(stream))
    assert events[-1] == LoopStopped(reason, 1, 1)
    assert calls == ["model", action]


@pytest.mark.parametrize("budget_kind", ["model", "action", "tool"])
def test_shared_admission_stops_further_work(budget_kind):
    async def run():
        _, _, calls, stream = scenario(
            decision_budget=DecisionBudget(1, 100000, 800)
            if budget_kind == "model"
            else None,
            action_budget=ActionBudget(1, 0 if budget_kind == "tool" else 2)
            if budget_kind != "model"
            else None,
        )
        events = await collect(stream)
        assert events[-1].detail == "budget_exhausted"
        assert events[-1].reason == (
            "decision_failed" if budget_kind == "model" else "action_failed"
        )
        if budget_kind == "tool":
            assert calls == ["model"]
        else:
            assert calls.count("use_tool") == 1 and "answer" not in calls

    asyncio.run(run())


@pytest.mark.parametrize("count", [1, 2, 3])
def test_close_prevents_all_later_model_and_handler_calls(count):
    async def run():
        _, _, calls, stream = scenario(("answer_then_research", "answer"))
        for _ in range(count):
            await anext(stream)
        before = list(calls)
        await stream.aclose()
        await asyncio.sleep(0)
        assert calls == before
        assert calls.count("model") == 1

    asyncio.run(run())


def test_user_changes_intent_after_tool_before_feedback():
    async def run():
        root, state, calls, stream = scenario()
        await anext(stream)
        assert (await anext(stream)).stage == ConversationAction.USE_TOOL
        state[0] = replace(root, request_id="turn-2", user_message="换题")
        events = await collect(stream)
        assert events[-1].reason == "stale_context"
        assert calls == ["model", "use_tool"]

    asyncio.run(run())


def test_consumer_pause_after_decision_exhausts_total_timeout_without_actions(
    monkeypatch,
):
    async def run():
        from types import SimpleNamespace
        from src.application import conversation_bounded_loop as module

        clock = [100.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        _, _, calls, stream = scenario(limits=LoopLimits(timeout_seconds=1))
        await anext(stream)
        clock[0] += 2
        assert await anext(stream) == LoopStopped("timeout", 1, 0)
        await stream.aclose()
        assert calls == ["model"]

    asyncio.run(run())


def test_consumer_pause_after_tool_exhausts_total_timeout_without_next_model(
    monkeypatch,
):
    async def run():
        from types import SimpleNamespace
        from src.application import conversation_bounded_loop as module

        clock = [100.0]
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        _, _, calls, stream = scenario(limits=LoopLimits(timeout_seconds=1))
        await anext(stream)
        await anext(stream)
        clock[0] += 2
        assert await anext(stream) == LoopStopped("timeout", 1, 1)
        await stream.aclose()
        assert calls == ["model", "use_tool"]

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["model", "handler"])
def test_external_cancellation_reaches_active_adapter_and_never_continues(stage):
    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        async def blocked(_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        _, _, calls, stream = scenario(
            model=blocked if stage == "model" else None,
            handler=blocked if stage == "handler" else None,
        )
        if stage == "handler":
            await anext(stream)
        task = asyncio.create_task(anext(stream))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cancelled.wait(), 0.5)
        await stream.aclose()
        assert calls.count("model") == 1

    asyncio.run(run())


def test_handler_error_has_one_terminal_event_and_sanitized_output():
    async def handler(_):
        raise RuntimeError("private adapter payload")

    _, _, calls, stream = scenario(handler=handler)
    events = asyncio.run(collect(stream))
    assert events[-1] == LoopStopped("action_failed", 1, 0, True, "handler_error")
    assert "private" not in repr(events)
    assert calls == ["model", "use_tool"]


def test_tool_without_recorded_server_consumption_cannot_request_next_decision():
    async def handler(_):
        return "5"

    _, _, calls, stream = scenario(handler=handler)
    events = asyncio.run(collect(stream))
    assert events[-1] == LoopStopped("invalid_observation", 1, 1)
    assert calls == ["model", "use_tool"]


def test_changed_research_during_tool_is_rejected():
    async def run():
        _, state, calls, stream = scenario()

        async def unused(_):
            return ""

        await anext(stream)
        await anext(stream)
        state[0] = replace(
            state[0], active_research=ActiveResearch("other", 1, "新研究")
        )
        events = await collect(stream)
        assert events[-1].reason == "stale_context" and calls.count("model") == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_decisions", True),
        ("max_decisions", 0),
        ("max_decisions", 9),
        ("timeout_seconds", 0),
        ("timeout_seconds", float("inf")),
        ("action_timeout_seconds", 31),
        ("decision", None),
    ],
)
def test_invalid_limits_rejected(field, value):
    with pytest.raises(ValueError):
        LoopLimits(**{field: value})
