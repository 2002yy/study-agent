"""M3-QD-2b: the USE_TOOL seam as a real dispatch handler.

M3-QD-1 wrote ``SemanticToolHandler.run``, a plain method nothing called. This makes the
same check reachable from the production dispatcher, which is the only place a model's
tool name normally arrives.

Three things are deliberate:

* **Q-11 runs inside the handler, not before it.** The dispatcher cannot validate a tool
  name - it has no registry and no permission set - so the check has to happen where those
  exist. Doing it only in the caller would make "the caller forgot" a permission bypass.
* **A refusal is not an error.** ``ActionRefusal`` tells the dispatcher nothing ran, so the
  tool slot is returned and the outcome is *known*. Reporting a rejected tool name as
  ``handler_error`` would claim an unknown outcome and charge the search budget for a call
  that provably never happened.
* **The round runs off the event loop.** ``run_turn`` is synchronous and does real work;
  awaiting it directly would hold the loop for the whole search and make every other
  stream in the process late.

Known limit, stated rather than hidden: ``asyncio.to_thread`` cannot cancel a thread. When
the dispatcher's deadline fires, the observation is correctly reported as unknown, but the
worker keeps running until it notices its own cancellation hook. Cooperative cancellation
through ``SemanticResearchHost.should_cancel`` is the next slice; this one does not claim it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.application.conversation_action_dispatch import (
    ActionInvocation,
    ActionRefusal,
    RefusalKind,
)
from src.application.conversation_decision import ConversationAction
from src.web.semantic_admission import validate_tool_call
from src.web.semantic_research_host import SemanticResearchHost, TurnResult

# ``validate_tool_call`` reports *why* it refused in prose. The loop needs the structured
# classification to decide whether a reselection is safe, so the mapping is explicit here
# and an unrecognised reason falls back to the most restrictive kind.
_REFUSAL_KINDS: dict[str, RefusalKind] = {
    "unknown_tool": RefusalKind.TOOL_UNAVAILABLE,
    "action_not_tool_use": RefusalKind.TOOL_UNAVAILABLE,
    "tool_not_permitted": RefusalKind.PERMISSION_DENIED,
    "budget_exhausted": RefusalKind.TOOL_BUDGET_EXHAUSTED,
    "arguments_not_a_mapping": RefusalKind.ARGUMENTS_REJECTED,
}

# ``validate_tool_call`` compares against the enum *member name* ("USE_TOOL"), while
# ``ConversationAction``'s value is lowercase ("use_tool"). Mapping explicitly, instead of
# upper-casing whatever arrives, means an unexpected stage is refused rather than silently
# coerced into a tool call.
_VALIDATION_ACTION: dict[ConversationAction, str] = {ConversationAction.USE_TOOL: "USE_TOOL"}

# dispatch rejects an observation longer than this; the summary is cut before that happens
# so a long turn produces a short observation instead of an ``invalid_observation``.
OBSERVATION_CAP = 8000


@dataclass(frozen=True)
class TurnAuthorization:
    """Which action identities this handler may execute, and against what registry.

    ``operation_id`` is the turn's root identity: every planning round and every admitted
    model call derives its own id from it (``op#rN#stage``), so a receipt can be traced back
    to the turn that authorized it. This object grants no execution authority by itself -
    it is the input the handler checks against.
    """

    operation_id: str
    permitted: frozenset[str]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation_id, str)
            or not self.operation_id.strip()
            or len(self.operation_id) > 160
        ):
            raise ValueError("invalid_turn_operation_id")
        if not isinstance(self.permitted, frozenset) or not all(
            isinstance(name, str) and name.strip() for name in self.permitted
        ):
            raise ValueError("invalid_turn_permissions")


def summarize_turn(result: TurnResult) -> str:
    """Turn a research round into the text the next decision will be given.

    Written to be *useful to a planner*, not to be a log: it says what was searched, what
    new sources came back, and why the round stopped. A summary that only echoed the query
    would leave the next round with nothing to change direction on.
    """

    lines = [f"停止原因：{result.stop_reason or 'unknown'}"]
    for record in result.rounds:
        queries = "、".join(row.get("query", "") for row in record.queries) or "（无查询）"
        urls = "、".join(record.observation_urls) or "（无新来源）"
        lines.append(f"第 {record.round_index + 1} 轮：查询 {queries}；新来源 {urls}")
    if not result.rounds:
        lines.append("本轮未执行任何搜索轮次")
    return "\n".join(lines)[:OBSERVATION_CAP]


class SemanticTurnHandler:
    """Adapt ``SemanticResearchHost`` to the dispatcher's handler interface."""

    def __init__(
        self,
        host: SemanticResearchHost,
        *,
        registry: Mapping[str, Any],
        authorization: TurnAuthorization,
        tool_budget_remaining: Callable[[], int],
    ) -> None:
        self._host = host
        self._registry = registry
        self._authorization = authorization
        self._tool_budget_remaining = tool_budget_remaining
        self.refusals: list[str] = []
        self.rounds_run = 0

    @property
    def authorization(self) -> TurnAuthorization:
        return self._authorization

    async def __call__(self, invocation: ActionInvocation) -> str | ActionRefusal:
        validation_action = _VALIDATION_ACTION.get(invocation.stage)
        if validation_action is None:
            return self._refuse("action_not_tool_use")
        decision = validate_tool_call(
            action=validation_action,
            tool=invocation.proposal.tool or "",
            registry=self._registry,
            permitted=self._authorization.permitted,
            budget_remaining=self._tool_budget_remaining(),
        )
        if not decision.allowed:
            return self._refuse(decision.reason)
        latest = invocation.proposal.focus.strip() or self._host.episode.original_question
        result = await asyncio.to_thread(self._host.run_turn, latest)
        self.rounds_run += 1
        return summarize_turn(result)

    def _refuse(self, reason: str) -> ActionRefusal:
        self.refusals.append(reason)
        return ActionRefusal(
            reason, _REFUSAL_KINDS.get(reason, RefusalKind.PERMISSION_DENIED)
        )
