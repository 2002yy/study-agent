"""Single-consumer loop lifecycle receipts; no durable resume or replay."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import threading
from typing import AsyncGenerator, AsyncIterator

from src.application.conversation_action_dispatch import ActionEvent
from src.application.conversation_bounded_loop import LoopEvent, LoopStopped
from src.application.conversation_decision_runner import DecisionResult


@dataclass(frozen=True)
class LoopReceipt:
    request_id: str
    status: str = "ready"
    last_request_id: str = ""
    decision_steps: int = 0
    observations: int = 0
    stop_reason: str = ""
    detail: str = ""
    outcome_unknown: bool = False


class _SessionEvents:
    def __init__(self, session: ConversationLoopSession) -> None:
        self._session = session

    def __aiter__(self) -> AsyncIterator[LoopEvent]:
        return self

    async def __anext__(self) -> LoopEvent:
        return await self._session._next()

    async def aclose(self) -> None:
        await self._session.aclose()


class ConversationLoopSession:
    """Own a trusted loop stream once, with a read-only lifecycle receipt.

    events() claims a single consumer before any async work. Use aclosing() on
    its returned handle, including when no event is read. Receipts survive an
    in-process disconnect only; they contain no observation text and cannot
    authorize replay or prove that external effects were rolled back.
    """

    def __init__(
        self, request_id: str, stream: AsyncGenerator[LoopEvent, None]
    ) -> None:
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 160
        ):
            raise ValueError("invalid session request id")
        self._stream = stream
        self._receipt = LoopReceipt(request_id)
        self._claimed = False
        self._claim_lock = threading.Lock()
        self._closing = asyncio.Lock()
        self._close_requested = False
        self._pull: asyncio.Task[LoopEvent] | None = None

    @property
    def receipt(self) -> LoopReceipt:
        return self._receipt

    def events(self) -> _SessionEvents:
        with self._claim_lock:
            if self._claimed or self._close_requested:
                raise RuntimeError("conversation session already consumed")
            self._claimed = True
            self._receipt = replace(self._receipt, status="claimed")
        return _SessionEvents(self)

    async def _close_source(self) -> None:
        async with self._closing:
            try:
                await self._stream.aclose()
            except asyncio.CancelledError:
                self._receipt = replace(
                    self._receipt, status="cancelled", outcome_unknown=True
                )
                raise
            except Exception:
                self._receipt = replace(
                    self._receipt,
                    status="failed",
                    detail="close_error",
                    outcome_unknown=True,
                )
                raise RuntimeError("conversation session close failed") from None

    async def aclose(self) -> None:
        """Close a paused stream or cancel an active pull without restarting it."""
        self._close_requested = True
        if self._receipt.status not in {"stopped", "cancelled", "failed", "closed"}:
            self._receipt = replace(
                self._receipt,
                status="closed",
                outcome_unknown=self._receipt.outcome_unknown or self._pull is not None,
            )
        task = self._pull
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                caller = asyncio.current_task()
                if caller is not None and caller.cancelling():
                    self._receipt = replace(
                        self._receipt, status="cancelled", outcome_unknown=True
                    )
                    raise
            except StopAsyncIteration:
                pass
            except Exception:
                pass
        await self._close_source()

    async def _next(self) -> LoopEvent:
        if self._close_requested or self._receipt.status in {
            "stopped",
            "cancelled",
            "failed",
        }:
            raise StopAsyncIteration
        if self._pull is not None:
            raise RuntimeError("concurrent session reads are not allowed")
        self._receipt = replace(self._receipt, status="running")
        self._pull = asyncio.create_task(anext(self._stream))
        try:
            event = await self._pull
            if self._close_requested:
                raise StopAsyncIteration
            if isinstance(event, DecisionResult):
                self._receipt = replace(
                    self._receipt,
                    decision_steps=self._receipt.decision_steps + 1,
                    last_request_id=event.proposal.request_id
                    if event.proposal
                    else self._receipt.last_request_id,
                    outcome_unknown=self._receipt.outcome_unknown
                    or event.outcome_unknown,
                )
            elif isinstance(event, ActionEvent):
                self._receipt = replace(
                    self._receipt,
                    last_request_id=event.request_id,
                    observations=self._receipt.observations
                    + int(event.status == "observed"),
                    outcome_unknown=self._receipt.outcome_unknown
                    or event.outcome_unknown,
                )
            elif isinstance(event, LoopStopped):
                if (event.decision_steps, event.observations) != (
                    self._receipt.decision_steps,
                    self._receipt.observations,
                ):
                    raise ValueError("inconsistent terminal counts")
                self._receipt = replace(
                    self._receipt,
                    status="stopped",
                    stop_reason=event.reason,
                    detail=event.detail,
                    outcome_unknown=self._receipt.outcome_unknown
                    or event.outcome_unknown,
                )
                await self._close_source()
            else:
                raise ValueError("invalid loop event")
            return event
        except StopAsyncIteration:
            if not self._close_requested and self._receipt.status != "stopped":
                self._receipt = replace(
                    self._receipt,
                    status="failed",
                    detail="missing_terminal_event",
                    outcome_unknown=True,
                )
            await self._close_source()
            raise
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            explicitly_closed = self._close_requested and (
                caller is None or not caller.cancelling()
            )
            self._receipt = replace(
                self._receipt,
                status="closed" if explicitly_closed else "cancelled",
                outcome_unknown=True,
            )
            await self._close_source()
            if explicitly_closed:
                raise StopAsyncIteration from None
            raise
        except Exception:
            self._receipt = replace(
                self._receipt,
                status="failed",
                detail="stream_error",
                outcome_unknown=True,
            )
            await self._close_source()
            raise RuntimeError("conversation session failed") from None
        finally:
            self._pull = None
