"""Explicitly mounted, default-disabled provisional events API.

No global app registration, provider configuration, client-owned model inputs,
budget creation or answer publication. The host owns authorization and settling
the existing ChatTurn operation through on_closed.
"""

from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable

import anyio
from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from src.application.conversation_loop_session import (
    ConversationLoopSession,
    LoopReceipt,
)
from src.application.conversation_owned_binding import OwnedConversationUnavailable
from src.application.conversation_progress_stream import conversation_progress_stream


class ConversationEventsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1, max_length=160)


StartRun = Callable[[str, str, str], ConversationLoopSession]
Authorize = Callable[[Request, str, str, str], Awaitable[bool]]
OnClosed = Callable[[str, str, str, LoopReceipt], Awaitable[None]]

_MAX_REQUEST_BYTES = 4096
_BODY_TIMEOUT_SECONDS = 2.0


async def _read_command(request: Request) -> ConversationEventsRequest:
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal():
            raise HTTPException(400, "Invalid conversation request")
        # Compare strings first: arbitrarily long decimal headers never reach int().
        normalized = length.lstrip("0") or "0"
        if len(normalized) > 4 or int(normalized) > _MAX_REQUEST_BYTES:
            raise HTTPException(413, "Conversation request too large")

    async def read() -> bytes:
        body = bytearray()
        async for chunk in request.stream():
            if len(chunk) > _MAX_REQUEST_BYTES - len(body):
                raise HTTPException(413, "Conversation request too large")
            body.extend(chunk)
        return bytes(body)

    try:
        body = await asyncio.wait_for(read(), timeout=_BODY_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise HTTPException(408, "Conversation request timed out") from None
    try:
        value = json.loads(body)
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid conversation request") from None
    try:
        return ConversationEventsRequest.model_validate(value)
    except ValidationError:
        raise HTTPException(422, "Invalid conversation request") from None


def _discard(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


class _OwnedEventsResponse(StreamingResponse):
    def __init__(
        self,
        session: ConversationLoopSession,
        notify: Callable[[LoopReceipt], Awaitable[None]],
    ) -> None:
        self._session = session
        self._progress = conversation_progress_stream(session)
        self._notify = notify
        self._cleanup: asyncio.Task[None] | None = None

        async def body():
            async for frame in self._progress:
                yield frame.to_sse()

        super().__init__(
            body(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    async def _release(self) -> None:
        try:
            await self._progress.aclose()
        finally:
            await self._notify(self._session.receipt)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Cleanup also runs when sending headers fails before body starts.
            # A callback that ignores cancellation cannot hold HTTP open forever.
            if self._cleanup is None:
                self._cleanup = asyncio.create_task(self._release())
            with anyio.CancelScope(shield=True):
                done, _ = await asyncio.wait({self._cleanup}, timeout=1.0)
                if not done:
                    self._cleanup.cancel()
                    self._cleanup.add_done_callback(_discard)
                else:
                    try:
                        self._cleanup.result()
                    except Exception:
                        raise RuntimeError("conversation cleanup failed") from None


def create_conversation_events_router(
    *,
    start_run: StartRun,
    authorize: Authorize,
    on_closed: OnClosed,
    enabled: Callable[[], bool] = lambda: False,
) -> APIRouter:
    """Host callbacks are mandatory; mount explicitly and opt in server-side.

    on_closed owns operation settlement, not automatic answer publication. It
    must use the supplied operation identity/CAS and preserve unknown effects.
    Event IDs are display-only; Last-Event-ID replay is deliberately rejected.
    """
    if not all(callable(value) for value in (start_run, authorize, on_closed, enabled)):
        raise ValueError("invalid conversation endpoint policy")
    router = APIRouter(tags=["conversation-events"])

    @router.post("/chat/threads/{thread_id}/turns/{turn_id}/agent-events")
    async def events(
        request: Request,
        thread_id: str = Path(min_length=1, max_length=160),
        turn_id: str = Path(min_length=1, max_length=160),
    ):
        try:
            if enabled() is not True:
                raise HTTPException(404, "Conversation events unavailable")
            command = await _read_command(request)
            allowed = await authorize(request, thread_id, turn_id, command.operation_id)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Conversation events unavailable") from None
        if allowed is not True:
            raise HTTPException(403, "Conversation events unavailable")
        if request.headers.get("last-event-id"):
            raise HTTPException(409, "Conversation event replay is unavailable")
        try:
            session = start_run(thread_id, turn_id, command.operation_id)
            if not isinstance(session, ConversationLoopSession):
                raise ValueError("invalid owned session")

            async def notify(receipt: LoopReceipt) -> None:
                await on_closed(thread_id, turn_id, command.operation_id, receipt)

            return _OwnedEventsResponse(session, notify)
        except OwnedConversationUnavailable:
            raise HTTPException(409, "Conversation operation unavailable") from None
        except Exception:
            raise HTTPException(503, "Conversation events unavailable") from None

    return router
