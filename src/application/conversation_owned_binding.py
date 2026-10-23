"""Read-only owned ChatTurn binding for the opt-in DeepSeek service."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
import sqlite3
from typing import Callable, Mapping

from src.application.conversation_action_dispatch import ActionBudget, ActionHandler
from src.application.conversation_answer_runner import AnswerLimits
from src.application.conversation_bounded_loop import LoopLimits
from src.application.conversation_decision import ConversationAction, DecisionContext
from src.application.conversation_decision_context import (
    OwnedDecisionResearch,
    context_from_chat_snapshots,
)
from src.application.conversation_decision_runner import DecisionAdmission
from src.application.conversation_deepseek_service import DeepSeekConversationService
from src.application.conversation_loop_session import ConversationLoopSession
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.repositories.runtime_repository import (
    _chat_thread_from_row,
    _chat_turn_from_row,
)


class OwnedConversationUnavailable(ValueError):
    """Generic operation/snapshot failure; never disclose another thread."""


@dataclass(frozen=True)
class OwnedChatSnapshot:
    thread: ChatThread
    turn: ChatTurn
    turns: tuple[ChatTurn, ...]


def _identity(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise OwnedConversationUnavailable("conversation operation unavailable")


@dataclass(frozen=True)
class SQLiteChatSnapshotReader:
    path: Path | str

    def __call__(self, thread_id: str, turn_id: str) -> OwnedChatSnapshot:
        _identity(thread_id)
        _identity(turn_id)
        try:
            # mode=ro prevents initialization/creation/recovery writes. BEGIN
            # gives all three SELECTs one coherent SQLite snapshot.
            uri = Path(self.path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.25)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                connection.execute("BEGIN")
                thread = connection.execute(
                    "SELECT * FROM chat_threads WHERE id = ?", (thread_id,)
                ).fetchone()
                current = connection.execute(
                    "SELECT * FROM chat_turns WHERE id = ? AND thread_id = ?",
                    (turn_id, thread_id),
                ).fetchone()
                if thread is None or current is None:
                    raise OwnedConversationUnavailable(
                        "conversation operation unavailable"
                    )
                prior = connection.execute(
                    "SELECT * FROM chat_turns WHERE thread_id = ? AND status = 'completed' "
                    "AND (created_at < ? OR (created_at = ? AND id < ?)) "
                    "ORDER BY created_at DESC, id DESC LIMIT 6",
                    (thread_id, current["created_at"], current["created_at"], turn_id),
                ).fetchall()
                turn = _chat_turn_from_row(current)
                return OwnedChatSnapshot(
                    _chat_thread_from_row(thread),
                    turn,
                    tuple(_chat_turn_from_row(row) for row in reversed(prior))
                    + (turn,),
                )
        except (sqlite3.Error, ValueError, KeyError, IndexError):
            raise OwnedConversationUnavailable(
                "conversation operation unavailable"
            ) from None


@dataclass(frozen=True)
class ConversationContextInputs:
    available_tools: tuple[str, ...] = ()
    remaining_tool_calls: int = 0
    evidence_summary: str = ""
    active_research: OwnedDecisionResearch | None = None
    supports_queue: bool = False


@dataclass(frozen=True)
class OwnedRunResources:
    model_budget: DecisionAdmission
    action_budget: ActionBudget
    handlers: Mapping[ConversationAction, ActionHandler]
    loop_limits: LoopLimits = LoopLimits()
    answer_limits: AnswerLimits = AnswerLimits()


def _default_inputs(snapshot: OwnedChatSnapshot) -> ConversationContextInputs:
    return ConversationContextInputs()


@dataclass(frozen=True)
class OwnedConversationBinding:
    service: DeepSeekConversationService
    snapshots: Callable[[str, str], OwnedChatSnapshot]
    resources: Callable[[OwnedChatSnapshot], OwnedRunResources] = field(repr=False)
    inputs: Callable[[OwnedChatSnapshot], ConversationContextInputs] = _default_inputs

    def _snapshot(self, thread_id: str, turn_id: str) -> OwnedChatSnapshot:
        snapshot = self.snapshots(thread_id, turn_id)
        if (
            not isinstance(snapshot, OwnedChatSnapshot)
            or snapshot.thread.id != thread_id
            or snapshot.turn.id != turn_id
        ):
            raise OwnedConversationUnavailable("conversation operation unavailable")
        return snapshot

    def _context(
        self, snapshot: OwnedChatSnapshot, operation_id: str
    ) -> DecisionContext:
        try:
            values = self.inputs(snapshot)
            if not isinstance(values, ConversationContextInputs):
                raise ValueError("invalid host context inputs")
            return context_from_chat_snapshots(
                snapshot.thread,
                snapshot.turn,
                snapshot.turns,
                operation_id=operation_id,
                available_tools=values.available_tools,
                remaining_tool_calls=values.remaining_tool_calls,
                evidence_summary=values.evidence_summary,
                active_research=values.active_research,
                supports_queue=values.supports_queue,
            )
        except ValueError:
            raise OwnedConversationUnavailable(
                "conversation operation unavailable"
            ) from None

    def start(
        self,
        thread_id: str,
        turn_id: str,
        operation_id: str,
        *,
        should_cancel: Callable[[], bool] = lambda: False,
        turn_window_seconds: float | None = None,
        model_budget: DecisionAdmission | None = None,
    ) -> ConversationLoopSession:
        """Bind identifiers only. Host controls snapshots, tools, budgets and cancel.

        No turn/operation is created, completed, released or published here.
        The host must own that lifecycle and independently authorize callers.

        ``should_cancel`` is the host's own answer to "has this turn been abandoned", in
        production ``repository.turn_cancel_requested(turn_id, operation_id)``. Passing it
        through rather than letting this binding poll a repository keeps the read-only
        contract of this module intact.

        ``turn_window_seconds`` replaces only the loop's *total* deadline - the one number
        that is a property of the turn rather than of the run configuration. The decision
        cap, the per-action window and the decision limits still come from the supplied
        resources, so a caller cannot widen the safety bounds by asking for a longer turn.

        ``model_budget`` likewise exists so the turn - not the snapshot - can hand down the
        admission it intends to settle. Settling a different object than the loop reserved
        on would leave every call open forever, and the only way to make that impossible is
        to let the settlement owner pass its own admission in.
        """
        for value in (thread_id, turn_id, operation_id):
            _identity(value)
        if not callable(should_cancel):
            raise ValueError("invalid host cancel probe")
        snapshot = self._snapshot(thread_id, turn_id)
        context = self._context(snapshot, operation_id)
        resources = self.resources(snapshot)
        if not isinstance(resources, OwnedRunResources):
            raise ValueError("invalid host run resources")
        loop_limits = resources.loop_limits
        if turn_window_seconds is not None:
            loop_limits = replace(loop_limits, timeout_seconds=turn_window_seconds)
        admission = resources.model_budget if model_budget is None else model_budget
        if not callable(getattr(admission, "reserve", None)):
            raise ValueError("invalid host model admission")
        return self.service.start(
            context,
            current_context=lambda: self._context(
                self._snapshot(thread_id, turn_id), operation_id
            ),
            model_budget=admission,
            action_budget=resources.action_budget,
            handlers=resources.handlers,
            loop_limits=loop_limits,
            answer_limits=resources.answer_limits,
            should_cancel=should_cancel,
        )
