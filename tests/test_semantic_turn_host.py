"""M3-QD-2b acceptance: Q-11 runs inside the real dispatch handler.

The decision layer already refuses a tool that is not in ``available_tools``
(``validate_proposal``). That is not the check this file is about. It is about the three
ways the server can disagree with what the model was shown:

* the tool exists and was offered, but this turn's authorization does not include it;
* the tool was offered, but no executor is registered for it;
* the tool and the authorization are fine, but the budget is gone by the time it runs.

None of those are visible to the dispatcher, which is why the check has to happen in the
handler. A refused call must also leave the budget untouched: otherwise a model could
exhaust the search budget by proposing tools it is not allowed to use.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json
import time

import pytest

from src.application.conversation_action_dispatch import (
    ActionBudget,
    ActionInvocation,
    ActionRefusal,
    dispatch_conversation_action,
)
from src.application.conversation_bounded_loop import LoopStopped, run_conversation_loop
from src.application.conversation_decision import (
    ConversationAction,
    DecisionContext,
    validate_proposal,
)
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_loop_session import ConversationLoopSession
from src.web.semantic_research_host import RoundRecord, TurnResult
from src.web.semantic_turn_host import (
    OBSERVATION_CAP,
    SemanticTurnHandler,
    TurnAuthorization,
    summarize_turn,
)

QUESTION = "为什么 B+ 树适合数据库？"


class FakeEpisode:
    original_question = QUESTION


class FakeHost:
    """Stands in for the research host; the real one is covered by the QD-1 tests."""

    def __init__(self, rounds=None, delay: float = 0.0) -> None:
        self.episode = FakeEpisode()
        self.calls: list[str] = []
        self.delay = delay
        self.rounds = (
            rounds
            if rounds is not None
            else [
                RoundRecord(
                    round_index=0,
                    queries=({"query": "B+树 磁盘页"},),
                    observation_urls=("https://example.org/a",),
                    stop_reason="continue",
                    observation_seen_by_model=False,
                )
            ]
        )

    def run_turn(self, latest: str) -> TurnResult:
        self.calls.append(latest)
        if self.delay:
            time.sleep(self.delay)
        return TurnResult(rounds=list(self.rounds), stop_reason="budget_exhausted")


def context(**changes) -> DecisionContext:
    return replace(
        DecisionContext(
            "request-1",
            QUESTION,
            available_tools=("web_search",),
            remaining_tool_calls=1,
        ),
        **changes,
    )


def proposal(ctx, action="use_tool", tool="web_search", focus=QUESTION):
    return validate_proposal(
        {
            "schema": "conversation-decision-v1",
            "request_id": ctx.request_id,
            "action": action,
            "relation": "new_topic",
            "reason": "先搜索再回答",
            "focus": focus,
            "tool": tool,
            "target_run_id": None,
            "target_revision": None,
            "active_run_disposition": "none",
        },
        ctx,
    )


async def collect(stream):
    return [event async for event in stream]


def authorization(*, permitted=("web_search",), operation_id="op-1") -> TurnAuthorization:
    return TurnAuthorization(
        operation_id=operation_id, permitted=frozenset(permitted)
    )


def drive(*, handlers, budget=None, ctx=None):
    ctx = ctx or context()
    return asyncio.run(
        collect(
            dispatch_conversation_action(
                proposal(ctx),
                ctx,
                current_context=lambda: ctx,
                handlers={ConversationAction.USE_TOOL: handlers},
                budget=budget or ActionBudget(4, 1),
            )
        )
    )


# --------------------------------------------------------------------------------------
# The three disagreements between what the model saw and what the server allows.
# --------------------------------------------------------------------------------------


def test_a_tool_outside_the_turn_authorization_is_refused():
    host = FakeHost()
    handler = SemanticTurnHandler(
        host,
        registry={"web_search": object()},
        authorization=authorization(permitted=()),      # offered to the model, not permitted
        tool_budget_remaining=lambda: 1,
    )

    events = drive(handlers=handler)

    assert [event.status for event in events] == ["refused"], events
    # Nothing ran, so the outcome is known rather than unknown.
    assert events[0].attempted is False
    assert events[0].outcome_unknown is False
    assert host.calls == []
    assert handler.refusals == ["tool_not_permitted"]


def test_a_tool_with_no_registered_executor_is_refused():
    host = FakeHost()
    handler = SemanticTurnHandler(
        host,
        registry={},                                   # offered and permitted, but unbuilt
        authorization=authorization(),
        tool_budget_remaining=lambda: 1,
    )

    events = drive(handlers=handler)

    assert [event.status for event in events] == ["refused"]
    assert handler.refusals == ["unknown_tool"]
    assert host.calls == []


def test_a_tool_call_with_no_budget_left_is_refused_at_the_handler():
    host = FakeHost()
    handler = SemanticTurnHandler(
        host,
        registry={"web_search": object()},
        authorization=authorization(),
        tool_budget_remaining=lambda: 0,
    )

    events = drive(handlers=handler)

    assert [event.status for event in events] == ["refused"]
    assert handler.refusals == ["budget_exhausted"]
    assert host.calls == []


def test_a_refusal_does_not_spend_the_search_budget():
    """The DoS shape: refuse, refuse, refuse, and the real search never gets to run."""

    budget = ActionBudget(max_actions=4, max_tool_calls=1)
    ctx = context()
    refused_host = FakeHost()
    refused = SemanticTurnHandler(
        refused_host,
        registry={"web_search": object()},
        authorization=authorization(permitted=()),
        tool_budget_remaining=lambda: 1,
    )
    first = asyncio.run(
        collect(
            dispatch_conversation_action(
                proposal(ctx),
                ctx,
                current_context=lambda: ctx,
                handlers={ConversationAction.USE_TOOL: refused},
                budget=budget,
            )
        )
    )
    assert [event.status for event in first] == ["refused"]

    allowed_host = FakeHost()
    allowed = SemanticTurnHandler(
        allowed_host,
        registry={"web_search": object()},
        authorization=authorization(),
        tool_budget_remaining=lambda: 1,
    )
    # A different request identity: the claim is not reusable, only the tool slot was freed.
    second_ctx = replace(ctx, request_id="request-2")
    second = asyncio.run(
        collect(
            dispatch_conversation_action(
                proposal(second_ctx),
                second_ctx,
                current_context=lambda: second_ctx,
                handlers={ConversationAction.USE_TOOL: allowed},
                budget=budget,
            )
        )
    )

    assert [event.status for event in second] == ["observed"], second
    assert allowed_host.calls == [QUESTION]


# --------------------------------------------------------------------------------------
# The handler only serves the stage it was built for.
# --------------------------------------------------------------------------------------


def test_an_answer_stage_cannot_run_a_tool():
    host = FakeHost()
    handler = SemanticTurnHandler(
        host,
        registry={"web_search": object()},
        authorization=authorization(),
        tool_budget_remaining=lambda: 1,
    )

    ctx = context()
    refusal = asyncio.run(
        handler(ActionInvocation(proposal(ctx), ConversationAction.ANSWER))
    )

    assert isinstance(refusal, ActionRefusal)
    assert refusal.reason == "action_not_tool_use"
    assert host.calls == []


def test_the_tool_name_actually_reaches_the_observation():
    """The permitted path still executes, and the round becomes the observation."""

    host = FakeHost()
    handler = SemanticTurnHandler(
        host,
        registry={"web_search": object()},
        authorization=authorization(),
        tool_budget_remaining=lambda: 1,
    )

    events = drive(handlers=handler)

    assert [event.status for event in events] == ["observed"], events
    # The planner's own focus is what gets searched, not a fixed string.
    assert host.calls == [QUESTION]
    assert "budget_exhausted" in events[0].observation
    assert "https://example.org/a" in events[0].observation


# --------------------------------------------------------------------------------------
# The round runs off the event loop.
# --------------------------------------------------------------------------------------


def test_a_slow_round_does_not_block_the_event_loop():
    """Otherwise one search stalls every other stream in the process."""

    async def scenario():
        host = FakeHost(delay=0.3)
        handler = SemanticTurnHandler(
            host,
            registry={"web_search": object()},
            authorization=authorization(),
            tool_budget_remaining=lambda: 1,
        )
        ctx = context()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        ticking = asyncio.create_task(ticker())
        events = await collect(
            dispatch_conversation_action(
                proposal(ctx),
                ctx,
                current_context=lambda: ctx,
                handlers={ConversationAction.USE_TOOL: handler},
                budget=ActionBudget(4, 1),
            )
        )
        ticking.cancel()
        try:
            await ticking
        except asyncio.CancelledError:
            pass
        return events, ticks

    events, ticks = asyncio.run(scenario())

    assert [event.status for event in events] == ["observed"]
    # A blocked loop would tick about once, not ~30 times.
    assert ticks >= 15, ticks


# --------------------------------------------------------------------------------------
# The observation must be usable by the next decision.
# --------------------------------------------------------------------------------------


def test_the_summary_names_the_sources_and_the_stop_reason():
    result = TurnResult(
        rounds=[
            RoundRecord(
                round_index=0,
                queries=({"query": "B+树 磁盘页"}, {"query": "B+树 扇出"}),
                observation_urls=("https://example.org/a", "https://example.org/b"),
                stop_reason="continue",
                observation_seen_by_model=False,
            ),
            RoundRecord(
                round_index=1,
                queries=({"query": "B+树 叶子链表"},),
                observation_urls=(),
                stop_reason="no_new_direction",
                observation_seen_by_model=True,
            ),
        ],
        stop_reason="no_new_direction",
    )

    summary = summarize_turn(result)

    assert "B+树 磁盘页" in summary and "B+树 扇出" in summary
    assert "https://example.org/a" in summary and "https://example.org/b" in summary
    assert "第 2 轮" in summary and "（无新来源）" in summary
    assert "no_new_direction" in summary


def test_a_turn_with_no_rounds_still_yields_a_non_empty_observation():
    """dispatch rejects empty observations; this must not depend on luck."""

    summary = summarize_turn(TurnResult(rounds=[], stop_reason="budget_exhausted"))

    assert summary.strip()
    assert "budget_exhausted" in summary


def test_a_very_long_turn_is_cut_before_dispatch_would_reject_it():
    rounds = [
        RoundRecord(
            round_index=index,
            queries=tuple({"query": "q" * 500} for _ in range(8)),
            observation_urls=tuple(f"https://example.org/{index}/{n}" for n in range(5)),
            stop_reason="continue",
            observation_seen_by_model=False,
        )
        for index in range(8)
    ]

    summary = summarize_turn(TurnResult(rounds=rounds, stop_reason="continue"))

    assert len(summary) <= OBSERVATION_CAP
    assert summary.strip()


# --------------------------------------------------------------------------------------
# Authorization itself is validated, not trusted.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("operation_id", ["", "   ", 5, None, "x" * 161])
def test_an_unusable_operation_identity_is_refused(operation_id):
    with pytest.raises(ValueError):
        TurnAuthorization(operation_id=operation_id, permitted=frozenset({"web_search"}))


@pytest.mark.parametrize("permitted", [{"web_search"}, ("web_search",), "web_search"])
def test_permissions_must_be_an_immutable_set_so_they_cannot_be_widened(permitted):
    with pytest.raises(ValueError):
        TurnAuthorization(operation_id="op-1", permitted=permitted)


# --------------------------------------------------------------------------------------
# Inside the real loop, a refusal must be distinguishable from a failure.
# --------------------------------------------------------------------------------------


def test_the_real_loop_reports_a_refusal_as_its_own_stop_reason():
    """QD-2c keeps the refusal *record* intact while allowing one reselection.

    The model below repeats the identical forbidden request. That is precisely what the
    contract says must not be executed, so the loop stops with `refused_tool_repeated`
    before dispatch - it does not reach the adapter a second time. The refusal itself is
    still reported as `refused` with a known outcome, which is the QD-2b guarantee.
    """
    async def scenario():
        host = FakeHost()
        handler = SemanticTurnHandler(
            host,
            registry={"web_search": object()},
            authorization=authorization(permitted=()),
            tool_budget_remaining=lambda: 1,
        )
        ctx = context()

        async def transport(request):
            messages = [{"role": r, "content": c} for r, c in request.messages]
            payload = json.loads(messages[1]["content"])
            return json.dumps(
                {
                    "schema": "conversation-decision-v1",
                    "request_id": payload["request_id"],
                    "action": "use_tool",
                    "relation": "continuation",
                    "reason": "需要搜索",
                    "focus": QUESTION,
                    "tool": "web_search",
                    "target_run_id": None,
                    "target_revision": None,
                    "active_run_disposition": "none",
                },
                ensure_ascii=False,
            )

        events = []
        session = ConversationLoopSession(
            "request-1",
            run_conversation_loop(
                ctx,
                current_context=lambda: ctx,
                transport=transport,
                decision_budget=DecisionBudget(2, 100_000, 1_600),
                action_budget=ActionBudget(2, 1),
                handlers={ConversationAction.USE_TOOL: handler},
            ),
        )
        async with aclosing(session.events()) as stream:
            async for event in stream:
                events.append(event)
        return events, host, session

    events, host, session = asyncio.run(scenario())

    refused = [event for event in events if getattr(event, "status", "") == "refused"]
    assert len(refused) == 1
    assert refused[0].refusal_kind == "permission_denied"
    assert refused[0].outcome_unknown is False

    stopped = [event for event in events if isinstance(event, LoopStopped)]
    assert len(stopped) == 1
    # The repeated identical request was blocked before dispatch, not re-run and re-refused.
    assert stopped[0].reason == "refused_tool_repeated", stopped[0]
    assert stopped[0].outcome_unknown is False
    assert stopped[0].observations == 0
    assert host.calls == []
    assert session.receipt.status == "stopped"
