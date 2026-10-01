"""§164-C1b: bounded, isolated execution for the shadow read.

The hook point in ``ChatService.start_turn`` is **synchronous**, so the isolation
this module provides is bounded synchronous execution rather than asyncio
scheduling: the shadow work runs on a worker thread with an explicit budget, and
the caller returns as soon as the budget is spent.

Contract, not technique (164.13):

- a shadow failure, a shadow stall or a shadow cancellation must never delay or
  cancel the production turn beyond the bounded budget;
- the caller always receives a result object and never an exception;
- a budget overrun yields ``unavailable`` and the legacy path continues.

No particular mechanism is promised here - only that the budget is enforced and
provable by test.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable

from src.domain.learner_state_parity import (
    SHADOW_ERROR,
    SHADOW_OK,
    SHADOW_UNAVAILABLE,
)

# First version budget. Deliberately a named constant rather than a tuned
# production parameter: C1 only has to prove the work is bounded, not to find the
# best number.
DEFAULT_SHADOW_BUDGET_SECONDS = 0.25


@dataclass(frozen=True)
class ShadowOutcome:
    """What the shadow produced, or why it produced nothing. Never an exception."""

    status: str
    value: object | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == SHADOW_OK


def run_shadow_bounded(
    work: Callable[[], object],
    *,
    budget_seconds: float = DEFAULT_SHADOW_BUDGET_SECONDS,
    on_telemetry: Callable[[object], None] | None = None,
) -> ShadowOutcome:
    """Run shadow work under a hard budget. Never raises, never blocks past it.

    ``on_telemetry`` is invoked best-effort after the budgeted read and outside
    any caller transaction; its own failure or slowness cannot affect the
    returned outcome, because it runs after the result is decided and its
    exceptions are swallowed.
    """
    if budget_seconds <= 0:
        return ShadowOutcome(SHADOW_UNAVAILABLE, None, "budget_not_positive")

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shadow-parity")
    try:
        future = executor.submit(work)
        try:
            value = future.result(timeout=budget_seconds)
        except FutureTimeout:
            # The budget is spent. We deliberately do not wait for the worker:
            # an overrun must not delay the turn, and a lingering worker is the
            # bounded cost of that guarantee.
            return ShadowOutcome(SHADOW_UNAVAILABLE, None, "budget_exceeded")
        except Exception as exc:  # noqa: BLE001 - fail-open is the contract
            return ShadowOutcome(SHADOW_ERROR, None, type(exc).__name__)
        except BaseException as exc:  # noqa: BLE001 - cancellation isolation
            # A shadow that is cancelled (or otherwise killed) must not cancel
            # the production turn: report and continue.
            return ShadowOutcome(SHADOW_ERROR, None, f"isolated:{type(exc).__name__}")
    finally:
        # shutdown(wait=False): the caller must not block on an overrun worker.
        executor.shutdown(wait=False)

    if on_telemetry is not None:
        try:
            on_telemetry(value)
        except Exception:  # noqa: BLE001 - telemetry may be dropped
            pass
    return ShadowOutcome(SHADOW_OK, value)


class BestEffortTelemetry:
    """Collector wrapper whose failures are always swallowed.

    ``chat turn success + parity artifact missing`` is a legal state; the reverse
    - a parity artifact that can fail or roll back a turn - is forbidden.
    """

    def __init__(self, sink: Any | None = None) -> None:
        self._sink = sink
        self.dropped = 0
        self.recorded = 0

    def record(self, observation: object) -> None:
        if self._sink is None:
            self.dropped += 1
            return
        try:
            self._sink.record(observation)
        except Exception:  # noqa: BLE001 - telemetry may be dropped
            self.dropped += 1
            return
        self.recorded += 1
