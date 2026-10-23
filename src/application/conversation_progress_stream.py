"""Display-only progress from one owned run; never evidence or publication."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import AsyncIterator

from src.application.conversation_action_dispatch import ActionEvent
from src.application.conversation_bounded_loop import LoopEvent, LoopStopped
from src.application.conversation_decision import ConversationAction
from src.application.conversation_decision_runner import DecisionResult
from src.application.conversation_loop_session import ConversationLoopSession


@dataclass(frozen=True)
class ConversationProgress:
    request_id: str
    sequence: int
    kind: str
    status: str
    text: str = ""
    phase: str = ""
    action: str = ""
    tool: str = ""
    focus: str = ""
    detail: str = ""
    decision_steps: int = 0
    observations: int = 0
    outcome_unknown: bool = False
    evidence_status: str = field(default="unverified", init=False)
    publication_status: str = field(default="provisional", init=False)

    @property
    def event_id(self) -> str:
        raw = json.dumps(
            ["conversation-progress-v1", self.request_id, self.sequence],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return "progress:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema": "conversation-progress-v1",
            "event_id": self.event_id,
            **asdict(self),
        }

    def to_sse(self) -> str:
        # Raw answer newlines are JSON-escaped, never executable SSE fields.
        return f"id: {self.event_id}\nevent: conversation_progress\ndata: {json.dumps(self.to_dict(), ensure_ascii=False, separators=(',', ':'))}\n\n"


class _ProgressStream:
    def __init__(self, session: ConversationLoopSession) -> None:
        self._session = session
        self._source = session.events()  # Claim now, so unread close works.
        self._sequence = 0
        self._ended = self._reading = False
        self._action: ConversationAction | None = None
        self._step_id = self._tool = ""
        self._stages: tuple[ConversationAction, ...] = ()

    def __aiter__(self) -> AsyncIterator[ConversationProgress]:
        return self

    def _frame(
        self, kind: str, status: str, *, unknown: bool = False, **values
    ) -> ConversationProgress:
        self._sequence += 1
        receipt = self._session.receipt
        return ConversationProgress(
            receipt.request_id,
            self._sequence,
            kind,
            status,
            decision_steps=receipt.decision_steps,
            observations=receipt.observations,
            outcome_unknown=receipt.outcome_unknown or unknown,
            **values,
        )

    def _project(self, event: LoopEvent) -> ConversationProgress:
        if isinstance(event, DecisionResult):
            self._action = None
            self._stages = ()
            if event.status != "completed":
                return self._frame("status", event.status)
            proposal = event.proposal
            if proposal is None:
                raise ValueError("missing progress proposal")
            self._action, self._step_id, self._tool = (
                proposal.action,
                proposal.request_id,
                proposal.tool or "",
            )
            self._stages = (
                (ConversationAction.ANSWER, ConversationAction.USE_TOOL)
                if proposal.action == ConversationAction.ANSWER_THEN_RESEARCH
                else (proposal.action,)
            )
            # Intent/focus is a plan, not a finding. Never expose reason/prompt.
            return self._frame(
                "status",
                "planned",
                action=proposal.action.value,
                tool=self._tool,
                focus=proposal.focus,
            )
        if isinstance(event, ActionEvent):
            if self._action is None or event.request_id != self._step_id:
                raise ValueError("unbound progress action")
            if event.stage is None and event.status != "observed":
                self._stages = ()
            elif not self._stages or event.stage != self._stages[0]:
                raise ValueError("unexpected progress stage")
            else:
                self._stages = self._stages[1:]
            kind, phase, text = "status", "", ""
            if event.status == "observed" and event.stage in {
                ConversationAction.ANSWER,
                ConversationAction.CLARIFY,
            }:
                if (
                    not isinstance(event.observation, str)
                    or not 0 < len(event.observation) <= 8000
                ):
                    raise ValueError("invalid progress content")
                kind = (
                    "answer"
                    if event.stage == ConversationAction.ANSWER
                    else "clarification"
                )
                phase = (
                    "preliminary"
                    if self._action == ConversationAction.ANSWER_THEN_RESEARCH
                    else "final"
                    if kind == "answer"
                    else "clarification"
                )
                text = event.observation
            return self._frame(
                kind,
                event.status,
                text=text,
                phase=phase,
                action=self._action.value,
                tool=self._tool if event.stage == ConversationAction.USE_TOOL else "",
            )
        if isinstance(event, LoopStopped):
            self._ended = True
            return self._frame("terminal", event.reason, detail=event.detail)
        raise ValueError("invalid progress event")

    async def __anext__(self) -> ConversationProgress:
        if self._ended:
            raise StopAsyncIteration
        if self._reading:
            raise RuntimeError("concurrent progress reads are not allowed")
        self._reading = True
        try:
            return self._project(await anext(self._source))
        except asyncio.CancelledError:
            self._ended = True
            raise
        except StopAsyncIteration:
            if not self._ended and self._session.receipt.status == "failed":
                self._ended = True
                return self._frame(
                    "terminal", "failed", detail=self._session.receipt.detail
                )
            self._ended = True
            raise
        except Exception:
            self._ended = True
            try:
                await self._source.aclose()
            except Exception:
                pass
            return self._frame(
                "terminal",
                "failed",
                unknown=True,
                detail=self._session.receipt.detail or "invalid_progress_event",
            )
        finally:
            self._reading = False

    async def aclose(self) -> None:
        self._ended = True
        await self._source.aclose()


def conversation_progress_stream(session: ConversationLoopSession) -> _ProgressStream:
    """Claim once; consume/close with aclosing. The host binds request to message.

    Answers remain provisional, tools expose metadata only, and terminal cleanup
    failure is an explicit failed frame. This is not an HTTP/ChatTurn writer.
    """
    if not isinstance(session, ConversationLoopSession):
        raise ValueError("invalid progress session")
    return _ProgressStream(session)
