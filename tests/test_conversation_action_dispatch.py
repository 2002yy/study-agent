"""Controlled action dispatch; scripted model choices are not live quality evidence."""

import asyncio
from dataclasses import asdict, replace
import json

import pytest

from src.application.conversation_action_dispatch import (
    ActionBudget,
    SteeringObservation,
    dispatch_conversation_action,
)
from src.application.conversation_decision import (
    ActiveResearch,
    ConversationAction,
    DecisionContext,
    validate_proposal,
)
from src.application.conversation_decision_runner import (
    DecisionBudget,
    decide_conversation_action,
)


def context(**changes):
    return replace(
        DecisionContext(
            "request-1",
            "先说明判断，再计算 2+3",
            available_tools=("compute",),
            remaining_tool_calls=1,
        ),
        **changes,
    )


def proposal(ctx, action="answer"):
    bound = action in {"steer", "queue"}
    return validate_proposal(
        {
            "schema": "conversation-decision-v1",
            "request_id": ctx.request_id,
            "action": action,
            "relation": "supplement" if action == "steer" else "new_topic",
            "reason": "需要先解释再执行有界动作",
            "focus": ctx.user_message,
            "tool": "compute"
            if action in {"use_tool", "answer_then_research"}
            else None,
            "target_run_id": ctx.active_research.run_id if bound else None,
            "target_revision": ctx.active_research.revision if bound else None,
            "active_run_disposition": "keep" if ctx.active_research else "none",
        },
        ctx,
    )


async def collect(stream):
    return [event async for event in stream]


def run(
    action="answer", *, ctx=None, handlers=None, budget=None, latest=None, timeout=5
):
    ctx = ctx or context()
    return asyncio.run(
        collect(
            dispatch_conversation_action(
                proposal(ctx, action),
                ctx,
                current_context=latest or (lambda: ctx),
                handlers=handlers or {},
                budget=budget or ActionBudget(4, 1),
                timeout_seconds=timeout,
            )
        )
    )


def test_model_choice_preliminary_answer_tool_observation_then_model_can_answer():
    async def scenario():
        ctx = context()
        calls = []

        async def initial_model(request):
            return json.dumps(
                {
                    "schema": "conversation-decision-v1",
                    **asdict(proposal(ctx, "answer_then_research")),
                }
            )

        decision = await decide_conversation_action(
            ctx,
            transport=initial_model,
            budget=DecisionBudget(1, 100000, 800),
            current_context=lambda: ctx,
        )
        assert decision.status == "completed"

        async def answer(invocation):
            calls.append("answer")
            return (
                "先给出比较方法，计算结果随后核对"
                if invocation.proposal.action == "answer_then_research"
                else "结果为 5"
            )

        async def compute(invocation):
            calls.append("compute")
            return str(sum((2, 3)))

        budget = ActionBudget(2, 1)
        handlers = {
            ConversationAction.ANSWER: answer,
            ConversationAction.USE_TOOL: compute,
        }
        stream = dispatch_conversation_action(
            decision.proposal,
            ctx,
            current_context=lambda: ctx,
            handlers=handlers,
            budget=budget,
        )
        first = await anext(stream)
        assert first.stage == "answer" and first.status == "observed"
        assert calls == ["answer"]  # useful stage can be consumed before tool starts
        second = await anext(stream)
        assert second.stage == "use_tool" and second.observation == "5"
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        updated = replace(
            ctx,
            request_id="request-2",
            evidence_summary="Unverified tool observation: " + second.observation,
        )

        async def next_model(request):
            data = json.loads(request.messages[1][1])
            assert data["evidence_summary"] == "Unverified tool observation: 5"
            return json.dumps(
                {"schema": "conversation-decision-v1", **asdict(proposal(updated))}
            )

        next_decision = await decide_conversation_action(
            updated,
            transport=next_model,
            budget=DecisionBudget(1, 100000, 800),
            current_context=lambda: updated,
        )
        events = await collect(
            dispatch_conversation_action(
                next_decision.proposal,
                updated,
                current_context=lambda: updated,
                handlers=handlers,
                budget=budget,
            )
        )
        assert events[0].observation == "结果为 5"
        assert calls == ["answer", "compute", "answer"]

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["answer", "clarify", "use_tool", "steer", "queue"])
def test_each_single_action_routes_only_to_its_registered_server_handler(action):
    ctx = context(
        active_research=ActiveResearch("run-1", 2, "原研究", True), supports_queue=True
    )
    calls = []

    async def handler(invocation):
        calls.append(invocation.stage)
        assert invocation.proposal.active_run_disposition == "keep"
        return "server observation"

    events = run(action, ctx=ctx, handlers={ConversationAction(action): handler})
    assert calls == [action] and events[0].attempted


def test_missing_second_adapter_cannot_partially_answer_or_consume_budget():
    ledger = ActionBudget(1, 1)
    calls = []

    async def handler(invocation):
        calls.append(invocation.stage)
        return "observation"

    events = run(
        "answer_then_research",
        handlers={ConversationAction.ANSWER: handler},
        budget=ledger,
    )
    assert events[0].status == "unsupported_action" and calls == []
    assert (
        run(handlers={ConversationAction.ANSWER: handler}, budget=ledger)[0].status
        == "observed"
    )


@pytest.mark.parametrize(
    "change",
    [
        "own",
        "later_revision",
        "new_topic",
        "no_receipt",
        "wrong_run",
        "old_revision",
        "non_steer",
    ],
)
def test_steering_revision_change_requires_exact_handler_owned_receipt(change):
    ctx = context(active_research=ActiveResearch("run-1", 2, "原研究", True))
    state = [ctx]
    committed = ActiveResearch("run-1", 3, "修正后的研究", True)

    async def handler(_):
        state[0] = replace(ctx, active_research=committed)
        if change == "later_revision":
            state[0] = replace(ctx, active_research=replace(committed, revision=4))
        if change == "new_topic":
            state[0] = replace(state[0], user_message="换题")
        if change == "no_receipt":
            return "已处理"
        receipt = committed
        if change == "wrong_run":
            receipt = replace(committed, run_id="other")
        if change == "old_revision":
            receipt = ctx.active_research
        return SteeringObservation("已处理", receipt)

    action = "answer" if change == "non_steer" else "steer"
    events = run(
        action,
        ctx=ctx,
        latest=lambda: state[0],
        handlers={ConversationAction(action): handler},
    )
    expected = (
        "observed"
        if change == "own"
        else (
            "invalid_observation"
            if change in {"wrong_run", "old_revision", "non_steer"}
            else "stale_context"
        )
    )
    assert events[0].status == expected and events[0].attempted
    assert events[0].observation == ("已处理" if change == "own" else "")


def test_concurrent_duplicate_dispatch_has_one_side_effect():
    async def scenario():
        ctx = context()
        ledger = ActionBudget(2, 1)
        calls = []

        async def handler(invocation):
            calls.append(invocation)
            await asyncio.sleep(0)
            return "one actual invocation"

        async def one():
            return await collect(
                dispatch_conversation_action(
                    proposal(ctx),
                    ctx,
                    current_context=lambda: ctx,
                    handlers={ConversationAction.ANSWER: handler},
                    budget=ledger,
                )
            )

        results = await asyncio.gather(one(), one())
        assert sorted(events[0].status for events in results) == [
            "already_dispatched",
            "observed",
        ]
        assert len(calls) == 1

    asyncio.run(scenario())


def test_tool_budget_exhaustion_and_forged_proposals_never_call_handlers():
    ctx = context()

    async def handler(invocation):
        pytest.fail("not authorized")

    handlers = {ConversationAction.USE_TOOL: handler}
    assert (
        run("use_tool", handlers=handlers, budget=ActionBudget(1, 0))[0].status
        == "budget_exhausted"
    )
    forged = replace(proposal(ctx, "use_tool"), tool="shell")
    events = asyncio.run(
        collect(
            dispatch_conversation_action(
                forged,
                ctx,
                current_context=lambda: ctx,
                handlers=handlers,
                budget=ActionBudget(1, 1),
            )
        )
    )
    assert events[0].status == "invalid_proposal"


def test_stale_context_between_scheduling_and_handler_start_is_rejected():
    async def scenario():
        ctx = context()
        state = [ctx]

        def latest():
            asyncio.get_running_loop().call_soon(
                lambda: state.__setitem__(0, replace(ctx, user_message="换个话题"))
            )
            return state[0]

        async def handler(invocation):
            pytest.fail("scheduled action is already stale")

        events = await collect(
            dispatch_conversation_action(
                proposal(ctx),
                ctx,
                current_context=latest,
                handlers={ConversationAction.ANSWER: handler},
                budget=ActionBudget(1, 1),
            )
        )
        assert events[0].status == "stale_context" and not events[0].attempted

    asyncio.run(scenario())


def test_changed_context_after_preliminary_answer_stops_tool_and_closing_stream_also_stops_it():
    async def scenario(close):
        ctx = context()
        state = [ctx]
        calls = []

        async def answer(invocation):
            return "initial useful analysis"

        async def tool(invocation):
            calls.append(invocation)
            return "tool observation"

        stream = dispatch_conversation_action(
            proposal(ctx, "answer_then_research"),
            ctx,
            current_context=lambda: state[0],
            handlers={
                ConversationAction.ANSWER: answer,
                ConversationAction.USE_TOOL: tool,
            },
            budget=ActionBudget(1, 1),
        )
        assert (await anext(stream)).stage == "answer"
        if close:
            await stream.aclose()
        else:
            state[0] = replace(ctx, user_message="新问题")
            assert (await anext(stream)).status == "stale_context"
            await stream.aclose()
        assert calls == []

    asyncio.run(scenario(False))
    asyncio.run(scenario(True))


@pytest.mark.parametrize("content", ["", "x" * 8001, None])
def test_invalid_tool_observations_are_not_forwarded(content):
    async def handler(invocation):
        return content

    events = run("use_tool", handlers={ConversationAction.USE_TOOL: handler})
    assert events[0].status == "invalid_observation" and events[0].observation == ""


def test_handler_self_cancellation_and_private_errors_are_controlled():
    for error in (asyncio.CancelledError, RuntimeError("private prompt or credential")):

        async def handler(invocation):
            raise error

        result = run(handlers={ConversationAction.ANSWER: handler})[0]
        assert result.status == "handler_error" and result.outcome_unknown
        assert "private" not in repr(result)


@pytest.mark.parametrize(
    "error", [ValueError("stopped context"), RuntimeError("private read detail")]
)
def test_context_read_failure_is_not_reported_as_an_invalid_model_proposal(error):
    def unavailable():
        raise error

    event = run(latest=unavailable)[0]
    assert event.status == "context_unavailable" and not event.attempted
    assert "private" not in repr(event)


def test_tool_observation_survives_its_own_budget_and_evidence_updates():
    ctx = context()
    state = [ctx]

    async def tool(invocation):
        state[0] = replace(
            ctx, remaining_tool_calls=0, evidence_summary="new tool result"
        )
        return "5"

    events = run(
        "use_tool",
        handlers={ConversationAction.USE_TOOL: tool},
        latest=lambda: state[0],
    )
    assert events[0].status == "observed" and events[0].observation == "5"


def test_external_cancellation_stops_handler_and_keeps_dispatch_claim():
    async def scenario():
        ctx = context()
        started = asyncio.Event()
        stopped = asyncio.Event()
        ledger = ActionBudget(2, 1)

        async def handler(invocation):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        def stream():
            return dispatch_conversation_action(
                proposal(ctx),
                ctx,
                current_context=lambda: ctx,
                handlers={ConversationAction.ANSWER: handler},
                budget=ledger,
            )

        pending = asyncio.create_task(collect(stream()))
        await started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await asyncio.wait_for(stopped.wait(), timeout=1)
        assert (await collect(stream()))[0].status == "already_dispatched"

    asyncio.run(scenario())


def test_timeout_cancels_before_emitting_event_and_ignores_late_output():
    async def scenario():
        ctx = context()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        late_done = asyncio.Event()

        async def handler(invocation):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
                late_done.set()
                return "late output"

        stream = dispatch_conversation_action(
            proposal(ctx),
            ctx,
            current_context=lambda: ctx,
            handlers={ConversationAction.ANSWER: handler},
            budget=ActionBudget(1, 1),
            timeout_seconds=0.02,
        )
        event = await anext(stream)
        assert event.status == "timeout" and event.outcome_unknown
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        release.set()
        await asyncio.wait_for(late_done.wait(), timeout=1)
        await stream.aclose()
        assert event.observation == ""

    asyncio.run(scenario())
