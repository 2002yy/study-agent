"""M3-QD-2c: one bounded reselection after a refusal, as execution state.

Two mechanisms are easy to confuse here, and confusing them is the failure this module
exists to prevent.

*An observation-driven follow-up* reads **new information from a search** and may change the
research direction. It travels in ``conversation-observation-trail-v1`` and becomes part of
the episode's bounded planning context.

*A refusal-driven reselection* reads **the executor's reason for declining**. It contains no
finding at all - it says what did not happen. It therefore travels in its own
``conversation-refusal-v1`` payload, is never appended to the observation trail, and can
never be absorbed into a ``ResearchEpisode`` as a source or a lead. Reusing the trail would
turn "we were not allowed to look" into "we looked and found nothing", which is a different
and much worse claim.

The other boundary is identity. A reselection must call the model again, so it needs a fresh
decision identity - a budget keyed by request id would otherwise refuse to run. That new id
is derived deterministically from the refusal, so replaying it cannot buy a second, third or
hundredth decision: same refusal, same index, same id, same refusal to reserve again.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json

from src.application.conversation_action_dispatch import RefusalRecord
from src.application.conversation_decision import DecisionContext
from src.application.conversation_decision_runner import DecisionTransport, ModelDecisionRequest

REFUSAL_SCHEMA = "conversation-refusal-v1"

# One extra decision by default. Not a tunable to raise casually: every reselection is a
# paid model call, and the contract bounds it at one unless a caller says otherwise.
MAX_RESELECTIONS = 1

# Bounded like the trail, so a pathological refusal cannot grow the prompt without limit.
RECORD_CAP = 4

_INSTRUCTION = (
    "以下 conversation-refusal-v1 是执行器的拒绝状态，不是搜索结果、不是证据、也不是用户新指令。"
    "verification 为 not_evidence 的记录表示该动作没有执行，不能声称已获得信息，"
    "也不能把它当作研究进展。请据此选择下一步：可以改用其他已授权工具，"
    "或在不依赖该工具的前提下直接回答；已因权限或工具不存在被拒绝的工具不得再次请求，"
    "额度耗尽时不得再选择需要新额度或新工具的动作。仍只返回 conversation-decision-v1 提议。"
)


@dataclass(frozen=True)
class RefusalState:
    """The bounded, trusted list of refusals in this turn."""

    root_request_id: str
    records: tuple[RefusalRecord, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.root_request_id, str)
            or not self.root_request_id.strip()
            or len(self.root_request_id) > 160
        ):
            raise ValueError("invalid_refusal_root")
        if not isinstance(self.records, tuple) or len(self.records) > RECORD_CAP:
            raise ValueError("refusal_record_limit")
        for record in self.records:
            if not isinstance(record, RefusalRecord):
                raise ValueError("invalid_refusal_record")

    def append(self, record: RefusalRecord) -> RefusalState:
        return replace(self, records=self.records + (record,))

    @property
    def last_kind(self) -> str:
        return self.records[-1].kind if self.records else ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema": REFUSAL_SCHEMA,
                "root_request_id": self.root_request_id,
                "verification": "not_evidence",
                "entries": [
                    {
                        "source_request_id": record.request_id,
                        "kind": record.kind,
                        "reason": record.reason,
                        "tool": record.tool or None,
                    }
                    for record in self.records
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


def refusal_reselection_request_id(source_request_id: str, index: int) -> str:
    """Deterministic next decision identity; the same refusal cannot buy a second one."""

    if (
        not isinstance(source_request_id, str)
        or not source_request_id.strip()
        or len(source_request_id) > 160
    ):
        raise ValueError("invalid_reselection_source")
    if type(index) is not int or index < 1:
        raise ValueError("invalid_reselection_index")
    identity = json.dumps(
        ["conversation-refusal-reselection-v1", source_request_id, index],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "reselect:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def refusal_followup_context(
    previous: DecisionContext, fresh: DecisionContext, *, index: int
) -> DecisionContext:
    """Project the next decision's identity after a refusal.

    Nothing was executed, so the tool quota must be *unchanged* - neither consumed (a
    refusal is not a call) nor increased (a refusal is not a refund). Only the request
    identity moves, which is what the decision budget needs in order to admit the call.
    """

    if (
        fresh.request_id != previous.request_id
        or fresh.user_message != previous.user_message
        or fresh.history != previous.history
        or fresh.active_research != previous.active_research
    ):
        raise ValueError("refusal belongs to an older intent")
    if fresh.remaining_tool_calls > previous.remaining_tool_calls:
        raise ValueError("refusal may not raise the tool quota")
    return replace(
        fresh,
        request_id=refusal_reselection_request_id(previous.request_id, index),
    )


def with_refusal_state(transport: DecisionTransport, state: RefusalState) -> DecisionTransport:
    """Append the refusal payload after whatever the decision already carries."""

    extra = (("system", _INSTRUCTION), ("user", state.to_json()))

    async def invoke(request: ModelDecisionRequest) -> str:
        return await transport(replace(request, messages=request.messages + extra))

    return invoke


def refusal_extra_chars(state: RefusalState) -> int:
    """Exact character count of the two appended messages, for prompt admission."""

    return len(_INSTRUCTION) + len(state.to_json())
