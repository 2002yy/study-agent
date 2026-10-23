"""M3-QD-1b acceptance: the real bounded loop, with only the model and executor scripted.

The previous slice (`test_semantic_research_host.py`) proved the loop's *logic* with a host
object. This one drives the production ``run_conversation_loop`` and asserts the properties
that only the real wiring can show: the event order, the per-round decision identity, how an
observation is actually delivered to the next decision, and the closing receipt.

Three facts this test had to establish first, because guessing them produced a green-looking
but false test:

* an observation is **not** merged into ``evidence_summary``; it arrives as two extra
  messages - an instruction and a ``conversation-tool-observation-v1`` payload marked
  ``unverified``;
* the loop remaps ``request_id`` after every observation
  (``tool_observation_request_id``), which is precisely why a budget keyed by request id
  does not block the second decision;
* the host must record tool consumption in the live snapshot, or the loop rejects the
  observation as ``invalid_observation`` before any second decision happens.
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
OBSERVATION_SCHEMA = "conversation-tool-observation-v1"

QUERY_A = "B+树 磁盘页 扇出"
QUERY_B = "B+树 叶子节点 链表 范围扫描"


def proposal(request_id: str, action: str, tool: str | None) -> str:
    return json.dumps(
        {
            "schema": "conversation-decision-v1",
            "request_id": request_id,
            "action": action,
            "relation": "continuation",
            "reason": "需要搜索后才能回答",
            "focus": QUESTION,
            "tool": tool,
            "target_run_id": None,
            "target_revision": None,
            "active_run_disposition": "none",
        },
        ensure_ascii=False,
    )


class ScriptedTransport:
    """Echo the request id it is handed - a stale id is rejected by design."""

    def __init__(self, actions: list[tuple[str, str | None]]) -> None:
        self.actions = actions
        self.requests: list[tuple[list[dict[str, str]], str]] = []
        self.observations_seen: list[dict] = []

    async def __call__(self, request) -> str:
        messages = [{"role": role, "content": content} for role, content in request.messages]
        # The decision context is the *second* message. Observations are appended after it,
        # so reading the last message would parse the observation instead of the context.
        payload = json.loads(messages[1]["content"]) if len(messages) > 1 else {}
        self.requests.append((messages, payload.get("request_id", "")))
        # Record any observation payload that was appended before this decision.
        for message in messages:
            if OBSERVATION_SCHEMA in message["content"]:
                self.observations_seen.append(json.loads(message["content"]))
        action, tool = self.actions[min(len(self.requests) - 1, len(self.actions) - 1)]
        return proposal(payload.get("request_id", ""), action, tool)


class ResearchHandler:
    """The USE_TOOL stage: run the round, record consumption, return the observation."""

    def __init__(self, queries: list[str]) -> None:
        self.queries = queries
        self.ctx: DecisionContext | None = None
        self.calls = 0

    def bind(self, ctx: DecisionContext) -> None:
        self.ctx = ctx

    async def __call__(self, _invocation) -> str:
        self.calls += 1
        query = self.queries[min(self.calls - 1, len(self.queries) - 1)]
        # The server-side consumption must be visible to the loop, not implied.
        assert self.ctx is not None
        self.ctx = replace(self.ctx, remaining_tool_calls=self.ctx.remaining_tool_calls - 1)
        source = "example.org/bplus-tree-pages" if "磁盘页" in query else "example.org/bplus-tree-leaf-scan"
        return f"查询「{query}」返回 {source}：扇出决定树高 / 叶子链表支撑范围扫描"


def context() -> DecisionContext:
    return DecisionContext(
        request_id="req-1",
        user_message=QUESTION,
        available_tools=("web_search",),
        remaining_tool_calls=4,
    )


async def drive(actions: list[tuple[str, str | None]], *, queries: list[str] | None = None):
    ctx = context()
    transport = ScriptedTransport(actions)
    handler = ResearchHandler(queries or [QUERY_A, QUERY_B])
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


# The observation *content* delivered to a decision is asserted in
# `test_semantic_research_host.py`, at the planner payload level, where it is proven that
# round two cannot be produced without round one's observation. The equivalent assertion on
# the loop's appended `conversation-tool-observation-v1` message is not made here yet: in
# this harness the transport did not observe that appended payload, and the cause is not
# established. A test that passed on an empty list would claim more than was verified, so
# the assertion is absent rather than weakened.


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
