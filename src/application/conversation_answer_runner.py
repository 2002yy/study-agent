"""Single-attempt answer generation through a trusted injected transport.

No SDK, currency ledger or publication authority. A deployment adapter must
disable hidden retries and reserve actual spend before sending paid requests.
Admission is never refunded, including failed, stale and cancelled attempts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import math
import time
from typing import Awaitable, Callable

from src.application.conversation_answer_input import AnswerInput
from src.application.conversation_decision import DecisionContext
from src.application.conversation_decision_runner import DecisionAdmission


@dataclass(frozen=True)
class AnswerLimits:
    timeout_seconds: float = 5.0
    max_output_tokens: int = 1200
    max_response_chars: int = 8000

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("invalid answer timeout")
        for value, cap in (
            (self.max_output_tokens, 4000),
            (self.max_response_chars, 8000),
        ):
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError("invalid answer output limit")


@dataclass(frozen=True)
class ModelAnswerRequest:
    call_id: str
    messages: tuple[tuple[str, str], ...]
    timeout_seconds: float
    max_output_tokens: int
    max_attempts: int = 1


@dataclass(frozen=True)
class AnswerResult:
    status: str
    answer: str = ""
    attempted: bool = False
    outcome_unknown: bool = False
    elapsed_seconds: float = 0.0


AnswerTransport = Callable[[ModelAnswerRequest], Awaitable[str]]


def answer_request_id(value: AnswerInput) -> str:
    """Stable stage identity, independent of mutable content or model wording.

    Namespace differs from decision admission; both may share the same ledger.
    An admitted ANSWER stage cannot be recharged by changing its proposal phase.
    """
    identity = json.dumps(
        ["conversation-answer-v1", value.context.request_id, "answer"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "answer:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


class _NotStarted(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


def _discard_late(task: asyncio.Task[str]) -> None:
    if not task.cancelled():
        task.exception()


async def generate_conversation_answer(
    value: AnswerInput,
    *,
    current_context: Callable[[], DecisionContext],
    transport: AnswerTransport,
    budget: DecisionAdmission,
    limits: AnswerLimits = AnswerLimits(),
) -> AnswerResult:
    """Bounded generation, not a citation/evidence or answer publication gate."""
    if not isinstance(value, AnswerInput):
        raise ValueError("invalid answer input")
    started = time.monotonic()
    submitted = False

    def result(status: str, *, unknown: bool = False, answer: str = "") -> AnswerResult:
        return AnswerResult(
            status, answer, submitted, unknown, time.monotonic() - started
        )

    def check_current() -> str:
        try:
            return "" if current_context() == value.context else "stale_context"
        except Exception:
            return "context_unavailable"

    # A pending caller cancellation must win before reservation or submission.
    await asyncio.sleep(0)
    status = check_current()
    if status:
        return result(status)
    messages = value.messages
    identity = answer_request_id(value)
    if time.monotonic() - started >= limits.timeout_seconds:
        return result("timeout")
    try:
        admission = budget.reserve(
            identity,
            sum(len(content) for _, content in messages),
            limits.max_output_tokens,
        )
    except Exception:
        return result("admission_unavailable")
    if admission != "reserved":
        return result(
            admission
            if isinstance(admission, str)
            and admission in {"already_attempted", "budget_exhausted"}
            else "admission_unavailable"
        )

    async def invoke() -> str:
        nonlocal submitted
        # Reservation implementations may synchronously advance server state or
        # consume time. Revalidate inside the task immediately before transport.
        status = check_current()
        if status:
            raise _NotStarted(status)
        remaining = limits.timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise _NotStarted("timeout")
        request = ModelAnswerRequest(
            identity, messages, remaining, limits.max_output_tokens
        )
        submitted = True
        return await transport(request)

    task = asyncio.create_task(invoke())
    try:
        done, _ = await asyncio.wait(
            {task},
            timeout=max(0, limits.timeout_seconds - (time.monotonic() - started)),
        )
        if not done:
            return result("timeout", unknown=submitted)
        raw = task.result()
    except asyncio.CancelledError:
        caller = asyncio.current_task()
        if caller is not None and caller.cancelling():
            raise
        return result("provider_error", unknown=submitted)
    except _NotStarted as exc:
        return result(exc.status)
    except TimeoutError:
        return result("timeout", unknown=submitted)
    except Exception:
        return result("provider_error", unknown=submitted)
    finally:
        if not task.done():
            task.cancel()
        task.add_done_callback(_discard_late)

    if time.monotonic() - started >= limits.timeout_seconds:
        return result("timeout", unknown=submitted)
    status = check_current()
    if status:
        return result(status)
    if (
        not isinstance(raw, str)
        or not raw.strip()
        or len(raw) > limits.max_response_chars
    ):
        return result("invalid_response")
    return result("completed", answer=raw)
