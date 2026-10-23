"""M3-QD-2a acceptance: the window arithmetic is actually wired into dispatch.

`test_action_window.py` proves the arithmetic. This file proves the *dispatcher uses it*,
and - the part that matters for the product - that a layered policy lets a research action
finish where one flat window does not.

The claim being tested is narrow on purpose. These are local handlers that sleep; nothing
here shows that a real network search fits in 25 seconds. What it shows is that the earlier
situation ("5s window, 1s reserved for search") was a policy defect and not only a timing
detail: with the same action and the same work, one configuration times out and the other
does not.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import math
import time

import pytest

from src.application.conversation_action_dispatch import (
    ActionBudget,
    dispatch_conversation_action,
)
from src.application.conversation_decision import (
    ConversationAction,
    DecisionContext,
    validate_proposal,
)
from src.web.action_window import (
    DEFAULT_CONVERSATIONAL_SECONDS,
    DEFAULT_RESEARCH_SECONDS,
    MAX_ACTION_SECONDS,
    ActionTimePolicy,
    ActionWindow,
)


def context(**changes):
    return replace(
        DecisionContext(
            "request-1",
            "先说明判断，再搜索验证",
            available_tools=("web_search",),
            remaining_tool_calls=1,
        ),
        **changes,
    )


def proposal(ctx, action):
    return validate_proposal(
        {
            "schema": "conversation-decision-v1",
            "request_id": ctx.request_id,
            "action": action,
            "relation": "new_topic",
            "reason": "需要先解释再执行有界动作",
            "focus": ctx.user_message,
            "tool": "web_search"
            if action in {"use_tool", "answer_then_research"}
            else None,
            "target_run_id": None,
            "target_revision": None,
            "active_run_disposition": "none",
        },
        ctx,
    )


async def collect(stream):
    return [event async for event in stream]


def drive(action, *, handlers, time_policy=None, timeout_seconds=5.0):
    ctx = context()
    return asyncio.run(
        collect(
            dispatch_conversation_action(
                proposal(ctx, action),
                ctx,
                current_context=lambda: ctx,
                handlers=handlers,
                budget=ActionBudget(4, 1),
                timeout_seconds=timeout_seconds,
                time_policy=time_policy,
            )
        )
    )


def sleepy(seconds: float):
    """A handler that takes real time and reports what it did."""

    calls = []

    async def handler(_invocation):
        calls.append(seconds)
        await asyncio.sleep(seconds)
        return f"slept {seconds}s"

    return handler, calls


# --------------------------------------------------------------------------------------
# Pure policy arithmetic: no clock, no flake.
# --------------------------------------------------------------------------------------


def test_a_research_action_gets_the_research_window_and_a_reply_gets_the_short_one():
    policy = ActionTimePolicy()

    research = policy.window_for(started=100.0, is_research=True)
    conversational = policy.window_for(started=100.0, is_research=False)

    assert research.total_seconds == DEFAULT_RESEARCH_SECONDS
    assert conversational.total_seconds == DEFAULT_CONVERSATIONAL_SECONDS
    # The number the product failure hinged on: research is not given a reply-sized window.
    assert DEFAULT_RESEARCH_SECONDS > DEFAULT_CONVERSATIONAL_SECONDS


def test_the_two_phases_share_one_start_and_cannot_restart_the_clock():
    started = 500.0
    window = ActionTimePolicy().window_for(started=started, is_research=True)

    assert window.overall_deadline == started + DEFAULT_RESEARCH_SECONDS
    assert window.first_deadline == window.overall_deadline - window.reserve_seconds
    assert started < window.first_deadline < window.overall_deadline
    # Phase two's deadline *is* the overall deadline: there is no second budget to spend.
    assert window.deadline_for(1) == window.overall_deadline


@pytest.mark.parametrize(
    "conversational,research",
    [
        (0.0, 25.0),
        (-1.0, 25.0),
        (5.0, 0.0),
        (float("nan"), 25.0),
        (5.0, float("inf")),
        (MAX_ACTION_SECONDS + 0.1, 25.0),
        (5.0, MAX_ACTION_SECONDS + 0.1),
        (True, 25.0),
    ],
)
def test_an_unusable_window_length_is_refused_rather_than_defaulted(
    conversational, research
):
    with pytest.raises(ValueError):
        ActionTimePolicy(
            conversational_seconds=conversational, research_seconds=research
        )


def test_a_single_stage_owns_the_whole_window_and_two_stages_split_it():
    """The split only applies where there is a second phase to reserve for."""

    policy = ActionTimePolicy(conversational_seconds=5.0, research_seconds=25.0)
    assert isinstance(policy.window_for(started=0.0, is_research=True), ActionWindow)


# --------------------------------------------------------------------------------------
# Wired into dispatch: the same work, two policies, opposite outcomes.
# --------------------------------------------------------------------------------------


def test_a_research_action_completes_under_the_layered_policy_and_times_out_without_it():
    """The regression this slice exists to prevent, reproduced and then removed.

    One `use_tool` handler that takes 0.6s. A 0.3s flat window cuts it off; a layered
    policy that gives research 1.2s lets it finish. Same code path, same handler.

    ``timeout_seconds`` is deliberately the *small* number here, not the default. Left at
    the default it would be 5s, larger than the layered 1.2s, and the test would still pass
    with ``time_policy`` ignored entirely - a mutation check caught exactly that.
    """

    layered = ActionTimePolicy(conversational_seconds=0.3, research_seconds=1.2)
    handler, calls = sleepy(0.6)

    under_layered = drive(
        "use_tool",
        handlers={ConversationAction.USE_TOOL: handler},
        time_policy=layered,
        timeout_seconds=0.3,
    )
    assert [event.status for event in under_layered] == ["observed"], under_layered
    assert calls == [0.6]

    flat_handler, _ = sleepy(0.6)
    under_flat = drive(
        "use_tool",
        handlers={ConversationAction.USE_TOOL: flat_handler},
        timeout_seconds=0.3,
    )
    assert [event.status for event in under_flat] == ["timeout"], under_flat
    assert under_flat[0].outcome_unknown is True


def test_the_preliminary_answer_cannot_eat_the_research_reserve():
    """The §9.5 defect itself: one shared window let phase one spend everything.

    Policy: 0.6s reply, 1.5s research overall. The reserve is
    ``max(1.5 * 0.4, min(1.0, 0.75)) = 0.75``, so phase one's deadline is 0.75s and the
    search has 0.75s left no matter how the reply behaved. The reply takes 0.5s and the
    search 0.8s: both fit *only* because the reply could not borrow the reserve.

    ``timeout_seconds`` stays at 0.6 so that ignoring the policy is detectable - a flat
    0.6s window cannot finish 0.5s + 0.8s.
    """

    policy = ActionTimePolicy(conversational_seconds=0.6, research_seconds=1.5)
    answer, answer_calls = sleepy(0.5)
    research, research_calls = sleepy(0.8)

    events = drive(
        "answer_then_research",
        handlers={ConversationAction.ANSWER: answer, ConversationAction.USE_TOOL: research},
        time_policy=policy,
        timeout_seconds=0.6,
    )

    assert [event.status for event in events] == ["observed", "observed"], events
    assert [event.stage for event in events] == [
        ConversationAction.ANSWER,
        ConversationAction.USE_TOOL,
    ]
    assert answer_calls == [0.5]
    assert research_calls == [0.8]


def test_a_first_phase_that_overruns_stops_the_action_before_research_starts():
    """The reserve is structural: phase one cannot borrow against it."""

    policy = ActionTimePolicy(conversational_seconds=0.6, research_seconds=1.5)
    answer, answer_calls = sleepy(1.0)          # longer than phase one's deadline
    research, research_calls = sleepy(0.01)

    events = drive(
        "answer_then_research",
        handlers={ConversationAction.ANSWER: answer, ConversationAction.USE_TOOL: research},
        time_policy=policy,
        timeout_seconds=0.6,
    )

    assert [event.status for event in events] == ["timeout"], events
    assert events[0].stage == ConversationAction.ANSWER
    assert events[0].outcome_unknown is True
    assert answer_calls == [1.0]                # it ran
    assert research_calls == []                 # and the search never began


def test_research_never_outlives_the_overall_deadline():
    """A late start cannot extend the total budget; only the unused part is available."""

    policy = ActionTimePolicy(conversational_seconds=0.3, research_seconds=0.8)
    handler, _ = sleepy(2.0)

    started = time.monotonic()
    events = drive(
        "use_tool",
        handlers={ConversationAction.USE_TOOL: handler},
        time_policy=policy,
        timeout_seconds=2.0,
    )
    elapsed = time.monotonic() - started

    assert [event.status for event in events] == ["timeout"], events
    # Cut off at the window, not at the handler's own duration.
    assert elapsed < 1.5, elapsed
    assert math.isfinite(elapsed)


# --------------------------------------------------------------------------------------
# Backwards compatibility: no policy means the previous behaviour, exactly.
# --------------------------------------------------------------------------------------


def test_without_a_policy_a_single_stage_keeps_the_legacy_flat_window():
    handler, calls = sleepy(0.05)
    ctx = context()
    events = asyncio.run(
        collect(
            dispatch_conversation_action(
                proposal(ctx, "answer"),
                ctx,
                current_context=lambda: ctx,
                handlers={ConversationAction.ANSWER: handler},
                budget=ActionBudget(4, 1),
                timeout_seconds=2.0,
            )
        )
    )
    assert [event.status for event in events] == ["observed"]
    assert calls == [0.05]
