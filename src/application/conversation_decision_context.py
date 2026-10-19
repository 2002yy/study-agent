"""Read-only projection of server-owned chat snapshots for model decisions.

Call after the current turn is persisted. The caller must obtain coherent server
snapshots and refresh them through the runner's current_context callback. This
module neither reads client history nor performs a DB read or authority cutover.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Sequence

from src.application.conversation_decision import ActiveResearch, DecisionContext
from src.domain.runtime_entities import ChatThread, ChatTurn


@dataclass(frozen=True)
class OwnedDecisionResearch:
    thread_id: str
    research: ActiveResearch


def context_from_chat_snapshots(
    thread: ChatThread,
    turn: ChatTurn,
    turns: Sequence[ChatTurn],
    *,
    operation_id: str,
    available_tools: tuple[str, ...] = (),
    remaining_tool_calls: int = 0,
    evidence_summary: str = "",
    active_research: OwnedDecisionResearch | None = None,
    supports_queue: bool = False,
) -> DecisionContext:
    """Bind a decision to one live server operation and completed prior turns.

    Only the last six completed turns are included; each historical message is
    capped at 8000 characters. The current user message is never truncated.
    This validates snapshot ownership, not atomicity of the caller's DB reads.
    """
    for identity in (thread.id, turn.id, operation_id):
        if not isinstance(identity, str) or not identity.strip() or len(identity) > 160:
            raise ValueError("invalid server decision identity")
    if (
        thread.status != "active"
        or thread.active_operation_id != operation_id
        or thread.archive_after_cancel_operation_id is not None
        or turn.thread_id != thread.id
        or turn.operation_id != operation_id
        or turn.status not in {"pending", "streaming"}
        or turn.cancel_requested_at is not None
    ):
        raise ValueError("decision operation is not active or owned")
    if turn.assistant_message.strip():
        # Continued turns retain their partial reply in this field. The v1
        # context has no separate current-partial slot: reject instead of
        # silently omitting it or disguising it as completed history.
        raise ValueError("current partial reply is not supported in decision context")
    if any(item.thread_id != thread.id for item in turns):
        raise ValueError("decision history belongs to another thread")
    if len({item.id for item in turns}) != len(turns):
        raise ValueError("duplicate decision history identity")
    ordered = sorted(turns, key=lambda item: (item.created_at, item.id))
    current = next(
        (index for index, item in enumerate(ordered) if item.id == turn.id), None
    )
    if current is None or ordered[current] != turn:
        raise ValueError("current turn missing or inconsistent in server snapshot")
    if active_research is not None and active_research.thread_id != thread.id:
        raise ValueError("decision research belongs to another thread")

    prior = [item for item in ordered[:current] if item.status == "completed"][-6:]
    history = tuple(
        (role, content[:8000])
        for item in prior
        for role, content in (
            ("user", item.user_message),
            ("assistant", item.assistant_message),
        )
        if content.strip()
    )
    identity_json = json.dumps(
        ["conversation-decision-v1", thread.id, turn.id, operation_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return DecisionContext(
        request_id="decision_" + sha256(identity_json.encode("utf-8")).hexdigest(),
        user_message=turn.user_message,
        history=history,
        evidence_summary=evidence_summary,
        available_tools=available_tools,
        remaining_tool_calls=remaining_tool_calls,
        active_research=None if active_research is None else active_research.research,
        supports_queue=supports_queue,
    )
