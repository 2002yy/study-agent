"""M3-QD-1b acceptance: the real bounded loop, with only the model and executor scripted.

The previous slice (`test_semantic_research_host.py`) proved the loop's *logic* with a host
object. This one drives the production ``run_conversation_loop`` and asserts the properties
that only the real wiring can show: the event order, the per-round decision identity, how an
observation is actually delivered to the next decision, and the closing receipt.

Four facts this test had to establish first, because guessing them produced a green-looking
but false test:

* an observation is **not** merged into ``evidence_summary``, and it is **not** delivered as
  the one-shot ``conversation-tool-observation-v1`` pair used by the opt-in
  ``decide_after_tool_observation`` seam. The loop appends a *cumulative*
  ``conversation-observation-trail-v1`` pair, so round three still carries round one's
  observation. Matching the single-shot schema - or reading only the last message - finds
  nothing and would make a vacuous assertion look satisfied;
* the loop remaps ``request_id`` after every observation
  (``tool_observation_request_id``), which is precisely why a budget keyed by request id
  does not block the second decision;
* the host must record tool consumption in the live snapshot, or the loop rejects the
  observation as ``invalid_observation`` before any second decision happens;
* a proposal's ``focus`` is the only route from "the model read the observation" to "the
  executor ran query B". A handler that picks its query from its own list would prove the
  loop ran twice, not that the second run was caused by the first result.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import replace
import json

from src.application.conversation_action_dispatch import ActionBudget
from src.application.conversation_bounded_loop import LoopStopped, run_conversation_loop
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_loop_session import ConversationLoopSession

QUESTION = "为什么 B+ 树适合数据库？"
TRAIL_SCHEMA = "conversation-observation-trail-v1"

QUERY_A = "B+树 磁盘页 扇出"
QUERY_B = "B+树 叶子节点 链表 范围扫描"

# Only round one's result contains this fact. The scripted model searches the second
# direction when, and only when, it reads this token in the trail - so the second search is
# traceable to the first result rather than to the harness's call order.
#
# This constant is deliberately used on the *reading* side only. The executor below writes
# the fact as a literal. An earlier version shared one constant across both sides, which made
# the whole assertion immune to mutation: changing the token changed the observation too, so
# the model always found what it was looking for. Mutation testing caught that; a test that
# cannot fail is not evidence.
TRAIL_TOKEN = "扇出约 1200"
A_OBSERVED_FACT = "页 16KB 时扇出约 1200，树高 3 层"

FAILED_OBSERVATION = "查询失败：连接超时，无结果"


def proposal(
    request_id: str, action: str, tool: str | None, *, focus: str = QUESTION
) -> str:
    return json.dumps(
        {
            "schema": "conversation-decision-v1",
            "request_id": request_id,
            "action": action,
            "relation": "continuation",
            "reason": "需要搜索后才能回答",
            "focus": focus,
            "tool": tool,
            "target_run_id": None,
            "target_revision": None,
            "active_run_disposition": "none",
        },
        ensure_ascii=False,
    )


def trail_entries(messages: list[dict[str, str]]) -> list[dict]:
    """The observation entries the loop actually appended before this decision.

    The decision context is message 1; anything after it is appended by the loop. Returns
    ``[]`` when nothing was appended, which is the honest answer for round one. Both
    appended messages mention the schema, but only the ``user`` one *is* the payload - the
    preceding ``system`` message is prose, so parsing it as JSON raises. That mistake showed
    up as ``provider_error`` at round two.
    """
    for message in messages[2:]:
        if message["role"] == "user" and TRAIL_SCHEMA in message["content"]:
            return json.loads(message["content"])["entries"]
    return []


class ScriptedTransport:
    """Echo the request id it is handed - a stale id is rejected by design."""

    def __init__(self, actions: list[tuple[str, str | None]]) -> None:
        self.actions = actions
        self.requests: list[tuple[list[dict[str, str]], str]] = []
        self.trails_seen: list[list[dict]] = []

    async def __call__(self, request) -> str:
        messages = [{"role": role, "content": content} for role, content in request.messages]
        # The decision context is the *second* message. Observations are appended after it,
        # so reading the last message would parse the observation instead of the context.
        payload = json.loads(messages[1]["content"]) if len(messages) > 1 else {}
        self.requests.append((messages, payload.get("request_id", "")))
        self.trails_seen.append(trail_entries(messages))
        action, tool = self.actions[min(len(self.requests) - 1, len(self.actions) - 1)]
        return proposal(payload.get("request_id", ""), action, tool)


class TrailDrivenTransport:
    """A scripted model whose second query exists only because of the first result.

    Round one has no trail to read, so it searches ``QUERY_A``. Later rounds look for the
    token that only ``QUERY_A``'s result contains: present, the model searches a genuinely
    new direction; absent (or the observation failed), the model answers instead. The
    negative control below relies on exactly that absence.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[list[dict[str, str]], str]] = []
        self.trails_seen: list[list[dict]] = []

    async def __call__(self, request) -> str:
        messages = [{"role": role, "content": content} for role, content in request.messages]
        payload = json.loads(messages[1]["content"]) if len(messages) > 1 else {}
        request_id = payload.get("request_id", "")
        entries = trail_entries(messages)
        self.requests.append((messages, request_id))
        self.trails_seen.append(entries)

        observed = [entry for entry in entries if entry["kind"] == "tool_observation"]
        if not observed:
            return proposal(request_id, "use_tool", "web_search", focus=QUERY_A)
        if TRAIL_TOKEN in observed[-1]["content"]:
            return proposal(request_id, "use_tool", "web_search", focus=QUERY_B)
        return proposal(request_id, "answer", None)


class ResearchHandler:
    """The USE_TOOL stage: run the round, record consumption, return the observation."""

    def __init__(
        self,
        queries: list[str],
        *,
        query_from_proposal: bool = False,
        observation: str | None = None,
    ) -> None:
        self.queries = queries
        self.query_from_proposal = query_from_proposal
        self.forced_observation = observation
        self.ctx: DecisionContext | None = None
        self.calls = 0
        self.seen_focus: list[str] = []
        self.observations: list[str] = []

    def bind(self, ctx: DecisionContext) -> None:
        self.ctx = ctx

    async def __call__(self, invocation) -> str:
        self.calls += 1
        self.seen_focus.append(invocation.proposal.focus)
        if self.query_from_proposal:
            # The executor runs what the model asked for, not what the harness queued.
            query = invocation.proposal.focus
        else:
            query = self.queries[min(self.calls - 1, len(self.queries) - 1)]
        # The server-side consumption must be visible to the loop, not implied.
        assert self.ctx is not None
        self.ctx = replace(self.ctx, remaining_tool_calls=self.ctx.remaining_tool_calls - 1)
        if self.forced_observation is not None:
            observation = self.forced_observation
        elif "磁盘页" in query:
            observation = f"查询「{query}」返回 example.org/bplus-tree-pages：{A_OBSERVED_FACT}"
        else:
            observation = (
                f"查询「{query}」返回 example.org/bplus-tree-leaf-scan："
                "叶子层双向链表，范围扫描顺序读"
            )
        self.observations.append(observation)
        return observation


def context() -> DecisionContext:
    return DecisionContext(
        request_id="req-1",
        user_message=QUESTION,
        available_tools=("web_search",),
        remaining_tool_calls=4,
    )


async def drive(
    actions: list[tuple[str, str | None]] | None = None,
    *,
    transport=None,
    queries: list[str] | None = None,
    query_from_proposal: bool = False,
    observation: str | None = None,
):
    ctx = context()
    transport = (
        transport if transport is not None else ScriptedTransport(actions or [("answer", None)])
    )
    handler = ResearchHandler(
        queries if queries is not None else [QUERY_A, QUERY_B],
        query_from_proposal=query_from_proposal,
        observation=observation,
    )
    handler.bind(ctx)

    def current_context() -> DecisionContext:
        assert handler.ctx is not None
        return handler.ctx

    events: list[object] = []
    session = ConversationLoopSession(
        "req-1",
        run_conversation_loop(
            ctx,
            current_context=current_context,
            transport=transport,
            decision_budget=DecisionBudget(
                max_calls=4, max_prompt_chars=200_000, max_output_tokens=8_000
            ),
            action_budget=ActionBudget(max_actions=4, max_tool_calls=4),
            handlers={ConversationAction.USE_TOOL: handler},
        ),
    )
    async with aclosing(session.events()) as stream:
        async for event in stream:
            events.append(event)
    return events, transport, handler, session


def test_the_real_loop_runs_two_tool_rounds_and_then_answers():
    events, transport, handler, _ = asyncio.run(
        drive([("use_tool", "web_search"), ("use_tool", "web_search"), ("answer", None)])
    )

    assert handler.calls == 2
    assert len(transport.requests) == 3
    kinds = [type(event).__name__ for event in events]
    assert kinds[:2] == ["DecisionResult", "ActionEvent"]
    assert kinds[-1] == "LoopStopped"


def test_the_second_search_is_traceable_to_the_first_observation():
    """The acceptance in one test: B exists because of what A returned.

    Three things are checked separately, because any one of them alone would pass on a
    harness that merely called the executor twice.
    """

    _, transport, handler, _ = asyncio.run(
        drive(transport=TrailDrivenTransport(), query_from_proposal=True)
    )

    # 0. The fact round one returned and the token the model reads must be the same thing.
    #    If they drift apart the causality claim becomes vacuous, so this is asserted rather
    #    than assumed - it is the precondition for checks 1-3 below.
    assert A_OBSERVED_FACT in handler.observations[0]
    assert TRAIL_TOKEN in handler.observations[0]

    # 1. The executor ran the model's ``focus``, in order: A first, B second.
    assert handler.calls == 2
    assert handler.seen_focus == [QUERY_A, QUERY_B]

    # 2. Round two's payload carried round one's observation, verbatim and attributed.
    assert transport.trails_seen[0] == []                  # nothing to read yet
    second = transport.trails_seen[1]
    assert [entry["kind"] for entry in second] == ["tool_observation"]
    assert second[0]["content"] == handler.observations[0]
    assert second[0]["source_request_id"] == "req-1"
    assert second[0]["verification"] == "unverified"
    assert second[0]["tool"] == "web_search"

    # 3. The trail accumulates: round three still sees round one, not just the latest
    #    entry. A "last observation only" delivery would drop the first.
    third = transport.trails_seen[2]
    assert [entry["kind"] for entry in third] == ["tool_observation", "tool_observation"]
    assert third[0]["content"] == handler.observations[0]
    assert third[1]["content"] == handler.observations[1]
    assert third[0]["content"] != third[1]["content"]


def test_without_a_usable_first_observation_the_second_search_never_happens():
    """Negative control for causality: remove A's information and B disappears.

    Same model, same wiring; only round one's result is worthless. If the second search
    still ran, the "traceable to the observation" claim above would be about call order.
    """

    events, transport, handler, _ = asyncio.run(
        drive(
            transport=TrailDrivenTransport(),
            query_from_proposal=True,
            observation=FAILED_OBSERVATION,
        )
    )

    assert handler.calls == 1
    assert handler.seen_focus == [QUERY_A]
    assert len(transport.requests) == 2                    # search A, then answer
    # The model did receive the failed observation - it just could not derive B from it.
    assert [entry["kind"] for entry in transport.trails_seen[1]] == ["tool_observation"]
    assert transport.trails_seen[1][0]["content"] == FAILED_OBSERVATION
    stopped = [event for event in events if isinstance(event, LoopStopped)]
    assert stopped and stopped[0].observations == 1


def test_each_decision_gets_its_own_request_identity():
    """A budget keyed by request id would reject round two if the id never changed."""

    _, transport, _, _ = asyncio.run(
        drive([("use_tool", "web_search"), ("use_tool", "web_search"), ("answer", None)])
    )
    ids = [request_id for _, request_id in transport.requests]
    assert ids[0] == "req-1"
    assert len(set(ids)) == len(ids), ids


def test_the_loop_stops_with_a_receipt_rather_than_silently():
    events, _, _, session = asyncio.run(
        drive([("use_tool", "web_search"), ("use_tool", "web_search"), ("answer", None)])
    )
    stopped = [event for event in events if isinstance(event, LoopStopped)]
    assert len(stopped) == 1
    assert stopped[0].observations == 2
    assert session.receipt.status in {"stopped", "closed"}
    assert session.receipt.observations == 2


def test_an_unauthorized_tool_in_the_second_round_never_reaches_the_executor():
    """The negative control: a tool the context does not offer cannot start a round."""

    events, _, handler, _ = asyncio.run(
        drive([("use_tool", "web_search"), ("use_tool", "shell_exec"), ("answer", None)])
    )
    assert handler.calls == 1                      # the second proposal executed nothing
    stopped = [event for event in events if isinstance(event, LoopStopped)]
    assert stopped and stopped[0].reason == "decision_failed"
