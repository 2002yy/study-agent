"""Single-attempt, bounded model decisions through an injected async transport.

No provider SDK or production routing switch lives here. The injected transport
must disable hidden retries and perform any deployment-specific durable spend
reservation. Local reservations remain consumed after *any* submitted attempt;
timeout/cancellation does not prove that an upstream request was not billed.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

from src.application.conversation_decision import (
    ActionProposal,
    DecisionContext,
    decision_messages,
    validate_proposal,
)


@dataclass(frozen=True)
class DecisionLimits:
    timeout_seconds: float = 5.0
    max_output_tokens: int = 800
    max_response_chars: int = 16000

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("invalid decision timeout")
        for value, cap in (
            (self.max_output_tokens, 2000),
            (self.max_response_chars, 32000),
        ):
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError("invalid decision output limit")


@dataclass(frozen=True)
class ModelDecisionRequest:
    call_id: str
    messages: tuple[tuple[str, str], ...]
    timeout_seconds: float
    max_output_tokens: int
    max_attempts: int = 1


@dataclass
class DecisionBudget:
    """Process-local admission ledger, shared by concurrent decisions.

    This is not a currency ledger or a restart-safe idempotency store. Production
    wiring must supply those before making this seam externally reachable.
    """

    max_calls: int
    max_prompt_chars: int
    max_output_tokens: int
    _requests: set[str] = field(default_factory=set, init=False, repr=False)
    _prompt_chars: int = field(default=0, init=False, repr=False)
    _output_tokens: int = field(default=0, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        for value in (self.max_calls, self.max_prompt_chars, self.max_output_tokens):
            if type(value) is not int or value < 0:
                raise ValueError("invalid decision budget")

    def reserve(self, request_id: str, prompt_chars: int, output_tokens: int) -> str:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("invalid decision request id")
        if any(
            type(value) is not int or value < 0
            for value in (prompt_chars, output_tokens)
        ):
            raise ValueError("invalid decision reservation")
        with self._lock:
            if request_id in self._requests:
                return "already_attempted"
            if (
                len(self._requests) >= self.max_calls
                or self._prompt_chars + prompt_chars > self.max_prompt_chars
                or self._output_tokens + output_tokens > self.max_output_tokens
            ):
                return "budget_exhausted"
            self._requests.add(request_id)
            self._prompt_chars += prompt_chars
            self._output_tokens += output_tokens
            return "reserved"


@dataclass(frozen=True)
class DecisionResult:
    status: str
    proposal: ActionProposal | None = None
    attempted: bool = False
    outcome_unknown: bool = False
    elapsed_seconds: float = 0.0


DecisionTransport = Callable[[ModelDecisionRequest], Awaitable[str]]


class DecisionAdmission(Protocol):
    def reserve(
        self, request_id: str, prompt_chars: int, output_tokens: int
    ) -> str: ...


def _discard_late(task: asyncio.Task[str]) -> None:
    # Retrieve late exceptions; never publish or validate late model output.
    if not task.cancelled():
        task.exception()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate decision field")
        result[key] = value
    return result


async def decide_conversation_action(
    context: DecisionContext,
    *,
    transport: DecisionTransport,
    budget: DecisionAdmission,
    current_context: Callable[[], DecisionContext],
    limits: DecisionLimits = DecisionLimits(),
) -> DecisionResult:
    """Bound response waiting, consume one reservation, and reject stale output.

    Caller cancellation propagates; a submitted reservation is never refunded.
    A transport that suppresses cancellation may still run remotely, but its
    result cannot become an action proposal and this function will not wait.
    """
    started = time.monotonic()

    def result(status: str, *, unknown: bool = False) -> DecisionResult:
        return DecisionResult(
            status,
            attempted=True,
            outcome_unknown=unknown,
            elapsed_seconds=time.monotonic() - started,
        )

    # Let pending cancellation win before any admission or transport invocation.
    await asyncio.sleep(0)
    try:
        if current_context() != context:
            return DecisionResult("stale_context")
    except Exception:
        return DecisionResult("context_unavailable")
    messages = decision_messages(context)
    remaining = limits.timeout_seconds - (time.monotonic() - started)
    if remaining <= 0:
        return DecisionResult("timeout", elapsed_seconds=time.monotonic() - started)
    try:
        admission = budget.reserve(
            context.request_id,
            sum(len(item["content"]) for item in messages),
            limits.max_output_tokens,
        )
    except Exception:
        return DecisionResult("admission_unavailable")
    if admission != "reserved":
        return DecisionResult(
            admission
            if isinstance(admission, str)
            and admission in {"already_attempted", "budget_exhausted"}
            else "admission_unavailable"
        )
    request = ModelDecisionRequest(
        call_id=f"conversation-decision:{context.request_id}",
        messages=tuple((item["role"], item["content"]) for item in messages),
        timeout_seconds=remaining,
        max_output_tokens=limits.max_output_tokens,
    )

    async def invoke() -> str:
        if time.monotonic() - started >= limits.timeout_seconds:
            raise TimeoutError("decision deadline exhausted before transport")
        return await transport(request)

    task = asyncio.create_task(invoke())
    try:
        done, _ = await asyncio.wait(
            {task},
            timeout=max(0.0, limits.timeout_seconds - (time.monotonic() - started)),
        )
        if not done:
            return result("timeout", unknown=True)
        raw = task.result()
    except asyncio.CancelledError:
        caller = asyncio.current_task()
        if caller is not None and caller.cancelling():
            raise
        # Adapter-owned cancellation is a transport failure, not a request to
        # cancel the caller. Its reservation remains consumed and is not retried.
        return result("provider_error", unknown=True)
    except TimeoutError:
        return result("timeout", unknown=True)
    except Exception:
        # Never surface exception text: it may include credentials or prompts.
        return result("provider_error", unknown=True)
    finally:
        if not task.done():
            task.cancel()
        task.add_done_callback(_discard_late)

    # Local parsing and freshness validation cannot turn an expired result into
    # a successful decision, even when the transport stalls the event loop.
    if time.monotonic() - started >= limits.timeout_seconds:
        return result("timeout", unknown=True)
    try:
        if current_context() != context:
            return result("stale_context")
    except Exception:
        return result("context_unavailable")
    try:
        if not isinstance(raw, str) or len(raw) > limits.max_response_chars:
            return result("invalid_response")
        payload = json.loads(raw, object_pairs_hook=_unique_object)
        proposal = validate_proposal(payload, context)
    except (TypeError, ValueError, RecursionError):
        return result("invalid_response")
    if time.monotonic() - started >= limits.timeout_seconds:
        return result("timeout", unknown=True)
    return DecisionResult(
        "completed",
        proposal=proposal,
        attempted=True,
        elapsed_seconds=time.monotonic() - started,
    )
