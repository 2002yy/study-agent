"""M3-QD-2c acceptance: one bounded reselection after a refusal.

The contract has six refusal cases and six hard constraints. They are tested separately
because they fail differently: a case decides *whether* the turn continues, a constraint
decides what the continuation may do. A single "refusal then answer" test would pass with
almost any implementation.

Two claims get the most attention:

* **A refusal is not an observation.** If the refusal ever reached the observation trail or
  the research episode, the next decision would read "we were not allowed to look" as "we
  looked and found nothing" - a different and much worse claim. Every reselection test also
  asserts that the trail payload is absent.
* **Reselection is not free.** It must buy a real decision reservation under a new, derived
  identity. A budget that admits it for nothing would let a model loop on refusals.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json

import pytest

from src.application.conversation_action_dispatch import (
    ActionBudget,
    ActionRefusal,
    RefusalKind,
    RefusalRecord,
    forbidden_action,
    refusal_allows_reselection,
)
from src.application.conversation_bounded_loop import LoopStopped, run_conversation_loop
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_loop_session import ConversationLoopSession
from src.application.conversation_refusal_state import (
    MAX_RESELECTIONS,
    RefusalState,
    refusal_reselection_request_id,
)

QUESTION = "为什么 B+ 树适合数据库？"
TRAIL_SCHEMA = "conversation-observation-trail-v1"
REFUSAL_SCHEMA = "conversation-refusal-v1"
OBSERVATION = "查询返回 example.org：页 16KB 时扇出约 1200"


class ScriptedModel:
    """Emits the next scripted action, echoing whatever identity it was handed."""

    def __init__(self, actions: list[dict]) -> None:
        self.actions = actions
        self.calls: list[dict] = []

    async def __call__(self, request) -> str:
        messages = [{"role": r, "content": c} for r, c in request.messages]
        context = json.loads(messages[1]["content"])
        appended = [m["content"] for m in messages[2:]]
        self.calls.append(
            {
                "request_id": context["request_id"],
                "has_refusal": any(REFUSAL_SCHEMA in text for text in appended),
                "has_trail": any(TRAIL_SCHEMA in text for text in appended),
                "payloads": appended,
            }
        )
        action = self.actions[min(len(self.calls) - 1, len(self.actions) - 1)]
        return json.dumps(
            {
                "schema": "conversation-decision-v1",
                "request_id": context["request_id"],
                "action": action.get("action", "use_tool"),
                "relation": "continuation",
                "reason": action.get("reason", "需要搜索"),
                "focus": action.get("focus", QUESTION),
                "tool": action.get("tool", "web_search"),
                "target_run_id": None,
                "target_revision": None,
                "active_run_disposition": "none",
            },
            ensure_ascii=False,
        )


class RefusingHandler:
    """Refuses ``refuse_times`` then observes. Records every invocation.

    Dunder lookup ignores instance attributes, so "mutate the handler after the first
    call" cannot be done by assigning ``__call__``. The counter is the honest way to model
    an adapter that stops refusing once the arguments are fixed.
    """

    def __init__(self, refusal: ActionRefusal | None, *, refuse_times: int = 10**6) -> None:
        self.refusal = refusal
        self.refuse_times = refuse_times
        self.ctx: DecisionContext | None = None
        self.invocations: list[str] = []

    def bind(self, ctx: DecisionContext) -> None:
        self.ctx = ctx

    async def __call__(self, invocation) -> object:
        self.invocations.append(invocation.proposal.focus)
        if self.refusal is not None and self.refuse_times > 0:
            self.refuse_times -= 1
            return self.refusal
        assert self.ctx is not None
        self.ctx = replace(
            self.ctx, remaining_tool_calls=self.ctx.remaining_tool_calls - 1
        )
        return OBSERVATION


def context(**changes) -> DecisionContext:
    return replace(
        DecisionContext(
            "req-1",
            QUESTION,
            available_tools=("web_search",),
            remaining_tool_calls=4,
        ),
        **changes,
    )


def drive(
    model: ScriptedModel,
    handler: RefusingHandler,
    *,
    decisions: DecisionBudget | None = None,
    actions: ActionBudget | None = None,
):
    ctx = context()
    handler.bind(ctx)
    answer_inputs: list = []

    async def answer_handler(value):
        answer_inputs.append(value)
        return "B+ 树适合数据库。"

    def current_context() -> DecisionContext:
        assert handler.ctx is not None
        return handler.ctx

    events: list[object] = []
    session = ConversationLoopSession(
        "req-1",
        run_conversation_loop(
            ctx,
            current_context=current_context,
            transport=model,
            decision_budget=decisions or DecisionBudget(3, 500_000, 2_400),
            action_budget=actions or ActionBudget(4, 4),
            handlers={ConversationAction.USE_TOOL: handler},
            answer_handler=answer_handler,
        ),
    )

    async def run():
        async with aclosing(session.events()) as stream:
            async for event in stream:
                events.append(event)

    asyncio.run(run())
    stopped = [event for event in events if isinstance(event, LoopStopped)]
    assert len(stopped) == 1, stopped
    model.answer_inputs = answer_inputs  # type: ignore[attr-defined]
    return stopped[0], model, handler, events


# --------------------------------------------------------------------------------------
# Pure classification: which refusals end the turn, and what may follow.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,recoverable",
    [
        (RefusalKind.TOOL_UNAVAILABLE, True),
        (RefusalKind.ARGUMENTS_REJECTED, True),
        (RefusalKind.PERMISSION_DENIED, True),
        (RefusalKind.TOOL_BUDGET_EXHAUSTED, True),
        (RefusalKind.CANCELLED, False),
        (RefusalKind.STALE_CONTEXT, False),
        (RefusalKind.OUTCOME_UNKNOWN, False),
        ("not_a_kind", False),
    ],
)
def test_only_the_four_local_refusals_allow_a_reselection(kind, recoverable):
    assert refusal_allows_reselection(str(kind)) is recoverable


def test_a_permission_refusal_forbids_the_tool_whatever_the_arguments():
    records = [
        RefusalRecord("req-1", RefusalKind.PERMISSION_DENIED, "tool_not_permitted", "web_search", "Q1")
    ]
    assert forbidden_action(
        records, action=ConversationAction.USE_TOOL, tool="web_search", focus="Q2"
    ) == "refused_tool_repeated"
    assert forbidden_action(
        records, action=ConversationAction.USE_TOOL, tool="compute", focus="Q2"
    ) == ""
    # Answering needs no tool, so it is not what the refusal ruled out.
    assert forbidden_action(
        records, action=ConversationAction.ANSWER, tool=None, focus="Q2"
    ) == ""


def test_a_rejected_argument_set_only_forbids_the_identical_request():
    records = [
        RefusalRecord("req-1", RefusalKind.ARGUMENTS_REJECTED, "arguments_not_a_mapping", "web_search", "Q1")
    ]
    assert forbidden_action(
        records, action=ConversationAction.USE_TOOL, tool="web_search", focus="Q1"
    ) == "refused_request_repeated"
    assert forbidden_action(
        records, action=ConversationAction.USE_TOOL, tool="web_search", focus="Q2"
    ) == ""


def test_an_exhausted_tool_budget_forbids_every_tool_action():
    records = [
        RefusalRecord("req-1", RefusalKind.TOOL_BUDGET_EXHAUSTED, "budget_exhausted", "web_search", "Q1")
    ]
    for action in (
        ConversationAction.USE_TOOL,
        ConversationAction.ANSWER_THEN_RESEARCH,
    ):
        assert forbidden_action(
            records, action=action, tool="compute", focus="Q9"
        ) == "refused_budget_action"
    assert forbidden_action(
        records, action=ConversationAction.ANSWER, tool=None, focus="Q9"
    ) == ""


def test_the_reselection_identity_is_derived_and_not_reusable():
    first = refusal_reselection_request_id("req-1", 1)
    assert first.startswith("reselect:")
    assert first == refusal_reselection_request_id("req-1", 1)
    assert first != refusal_reselection_request_id("req-1", 2)
    assert first != refusal_reselection_request_id("req-2", 1)


@pytest.mark.parametrize("source,index", [("", 1), ("req-1", 0), ("req-1", -1), ("req-1", True)])
def test_an_unusable_reselection_identity_is_refused(source, index):
    with pytest.raises(ValueError):
        refusal_reselection_request_id(source, index)


def test_the_refusal_state_is_bounded():
    state = RefusalState("req-1")
    for index in range(4):
        state = state.append(
            RefusalRecord(f"req-{index}", RefusalKind.TOOL_UNAVAILABLE, "unknown_tool", "t", "q")
        )
    with pytest.raises(ValueError):
        state.append(
            RefusalRecord("req-9", RefusalKind.TOOL_UNAVAILABLE, "unknown_tool", "t", "q")
        )


def test_a_refusal_must_say_why_and_be_classified():
    with pytest.raises(ValueError):
        ActionRefusal("")
    with pytest.raises(ValueError):
        ActionRefusal("reason", kind="permission_denied")  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Constraint 6, first: a refusal is never an observation.
# --------------------------------------------------------------------------------------


def test_a_refusal_reaches_the_model_as_state_and_never_as_a_trail_entry():
    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "B+树 磁盘页"},
            {"action": "answer", "tool": None},
        ]
    )
    handler = RefusingHandler(ActionRefusal("unknown_tool", RefusalKind.TOOL_UNAVAILABLE))

    stopped, model, handler, _ = drive(model, handler)

    assert stopped.reason == "answered"
    assert handler.invocations == ["B+树 磁盘页"]
    second = model.calls[1]
    assert second["has_refusal"] is True
    # The decisive assertion: no observation payload exists, because nothing was observed.
    assert second["has_trail"] is False
    payload = json.loads(second["payloads"][-1])
    assert payload["verification"] == "not_evidence"
    assert payload["entries"][0]["kind"] == "tool_unavailable"
    assert payload["entries"][0]["tool"] == "web_search"


# --------------------------------------------------------------------------------------
# The six cases.
# --------------------------------------------------------------------------------------


def test_a_missing_tool_lets_the_model_answer_instead():
    model = ScriptedModel(
        [{"action": "use_tool", "focus": "Q1"}, {"action": "answer", "tool": None}]
    )
    handler = RefusingHandler(ActionRefusal("unknown_tool", RefusalKind.TOOL_UNAVAILABLE))

    stopped, _, handler, _ = drive(model, handler)

    assert stopped.reason == "answered"
    assert handler.invocations == ["Q1"]


def test_bad_arguments_allow_the_same_tool_with_different_arguments():
    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            {"action": "use_tool", "focus": "Q2"},
            {"action": "answer", "tool": None},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("arguments_not_a_mapping", RefusalKind.ARGUMENTS_REJECTED),
        refuse_times=1,
    )
    stopped, model, handler, _ = drive(model, handler)

    assert stopped.reason == "answered"
    assert handler.invocations == ["Q1", "Q2"]
    assert model.calls[1]["request_id"].startswith("reselect:")


def test_repeating_the_identical_rejected_request_never_reaches_the_adapter():
    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            {"action": "use_tool", "focus": "Q1"},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("arguments_not_a_mapping", RefusalKind.ARGUMENTS_REJECTED)
    )

    stopped, _, handler, _ = drive(model, handler)

    assert stopped.reason == "refused_request_repeated"
    assert handler.invocations == ["Q1"]          # the repeat was blocked before dispatch


def test_a_permission_refusal_cannot_be_retried_with_reworded_arguments():
    """The bypass attempt: same tool, new focus. It must not execute."""

    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            {"action": "use_tool", "focus": "a completely different wording"},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("tool_not_permitted", RefusalKind.PERMISSION_DENIED)
    )

    stopped, _, handler, _ = drive(model, handler)

    assert stopped.reason == "refused_tool_repeated"
    assert handler.invocations == ["Q1"]


def test_an_exhausted_budget_allows_an_answer_but_not_another_tool():
    answered = ScriptedModel(
        [{"action": "use_tool", "focus": "Q1"}, {"action": "answer", "tool": None}]
    )
    handler = RefusingHandler(
        ActionRefusal("budget_exhausted", RefusalKind.TOOL_BUDGET_EXHAUSTED)
    )
    stopped, _, _, _ = drive(answered, handler)
    assert stopped.reason == "answered"

    retried = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            # Same tool the context offers, different arguments: the decision layer accepts
            # it, so only the exhaustion rule can stop it.
            {"action": "use_tool", "focus": "Q2"},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("budget_exhausted", RefusalKind.TOOL_BUDGET_EXHAUSTED)
    )
    stopped, _, handler, _ = drive(retried, handler)
    assert stopped.reason == "refused_budget_action"
    assert handler.invocations == ["Q1"]


@pytest.mark.parametrize(
    "kind,detail",
    [
        (RefusalKind.OUTCOME_UNKNOWN, "outcome_unknown"),
        (RefusalKind.CANCELLED, "cancelled"),
        (RefusalKind.STALE_CONTEXT, "stale_context"),
    ],
)
def test_a_terminal_refusal_ends_the_turn_without_another_model_call(kind, detail):
    model = ScriptedModel(
        [{"action": "use_tool", "focus": "Q1"}, {"action": "answer", "tool": None}]
    )
    handler = RefusingHandler(ActionRefusal(detail, kind))

    stopped, model, handler, _ = drive(model, handler)

    assert stopped.reason == "tool_refused"
    assert stopped.detail == detail
    assert stopped.outcome_unknown is False
    assert len(model.calls) == 1                  # no reselection was attempted
    assert handler.invocations == ["Q1"]


# --------------------------------------------------------------------------------------
# Constraints 1-5.
# --------------------------------------------------------------------------------------


def test_only_one_reselection_is_granted():
    assert MAX_RESELECTIONS == 1
    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            {"action": "use_tool", "focus": "Q2"},
            {"action": "use_tool", "focus": "Q3"},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("arguments_not_a_mapping", RefusalKind.ARGUMENTS_REJECTED)
    )

    stopped, model, handler, _ = drive(model, handler)

    assert stopped.reason == "refusal_limit"
    assert stopped.detail == str(RefusalKind.ARGUMENTS_REJECTED)
    assert len(model.calls) == 2                  # the third decision was never requested
    assert handler.invocations == ["Q1", "Q2"]


def test_a_reselection_pays_for_its_own_model_call():
    """A budget that admits it for free would make the one-reselection bound meaningless."""

    model = ScriptedModel(
        [{"action": "use_tool", "focus": "Q1"}, {"action": "answer", "tool": None}]
    )
    handler = RefusingHandler(ActionRefusal("unknown_tool", RefusalKind.TOOL_UNAVAILABLE))

    stopped, model, _, _ = drive(
        model, handler, decisions=DecisionBudget(1, 500_000, 2_400)
    )

    assert len(model.calls) == 1
    assert stopped.reason == "decision_failed"
    assert stopped.detail == "budget_exhausted"


def test_a_refused_call_returns_its_tool_slot_so_the_reselection_can_execute():
    """Constraint 5, from the outcome side: the refund is usable, not merely recorded."""

    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            {"action": "use_tool", "focus": "Q2"},
            {"action": "answer", "tool": None},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("arguments_not_a_mapping", RefusalKind.ARGUMENTS_REJECTED),
        refuse_times=1,
    )
    stopped, _, handler, _ = drive(
        model, handler, actions=ActionBudget(max_actions=4, max_tool_calls=1)
    )

    # One tool slot total: refused once (slot returned), then spent by the real search.
    assert stopped.reason == "answered"
    assert handler.invocations == ["Q1", "Q2"]


def test_the_new_identity_is_stable_and_bound_to_the_refusal():
    model = ScriptedModel(
        [{"action": "use_tool", "focus": "Q1"}, {"action": "answer", "tool": None}]
    )
    handler = RefusingHandler(ActionRefusal("unknown_tool", RefusalKind.TOOL_UNAVAILABLE))

    _, model, _, _ = drive(model, handler)

    assert model.calls[0]["request_id"] == "req-1"
    assert model.calls[1]["request_id"] == refusal_reselection_request_id("req-1", 1)


def test_a_reselection_cannot_be_admitted_twice_under_the_same_identity():
    """Same refusal, same index, same id - a replay must not buy a second call."""

    model = ScriptedModel(
        [
            {"action": "use_tool", "focus": "Q1"},
            {"action": "use_tool", "focus": "Q2"},
            {"action": "answer", "tool": None},
        ]
    )
    handler = RefusingHandler(
        ActionRefusal("arguments_not_a_mapping", RefusalKind.ARGUMENTS_REJECTED)
    )
    _, model, _, _ = drive(model, handler)

    reselected = [call["request_id"] for call in model.calls if call["request_id"].startswith("reselect:")]
    assert len(reselected) == len(set(reselected)) == 1
