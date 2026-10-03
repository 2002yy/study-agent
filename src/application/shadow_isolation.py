"""§164-C1b-0: bounded-resource, isolated execution for the shadow read.

Latency isolation alone is not production-inert. ``shutdown(wait=False)`` only
means "I did not wait for it"; it does not mean "it stopped". A stalled reader on
a per-call executor would leave a live worker behind on every turn, so the single
call stays fast while threads grow without bound.

This module therefore bounds three resources, not just one:

- **workers**: one shared executor with a small fixed worker count;
- **admission**: a semaphore, so a saturated shadow rejects immediately instead of
  queueing (an unbounded default queue would just trade thread growth for queue
  growth);
- **telemetry**: a bounded queue with drop-on-overload and a single daemon
  flusher, so a slow sink cannot build an unbounded backlog.

It also reports honestly what happened: a caller timeout is recorded as
``timed_out`` with ``worker_termination_known=False``, never as "the worker was
cancelled", because a running Python thread cannot be safely killed.

Process control signals are deliberately *not* swallowed: business failure
isolation is not the same as masking KeyboardInterrupt or SystemExit.
"""

from __future__ import annotations

from concurrent.futures import (
    CancelledError,
    ThreadPoolExecutor,
    TimeoutError as FutureTimeout,
)
from dataclasses import dataclass
import queue
import threading
import time
from typing import Any, Callable

from src.domain.learner_state_parity import (
    SHADOW_ERROR,
    SHADOW_OK,
    SHADOW_UNAVAILABLE,
)

# First version budget. Deliberately a named constant rather than a tuned
# production parameter: C1 only has to prove the work is finite and bounded, not
# to find the right number. C2 measures the real distribution.
DEFAULT_SHADOW_BUDGET_SECONDS = 0.25

# Small and fixed. Shadow work is optional measurement; it never deserves a pool.
#
# Admission equals workers on purpose: the standard ThreadPoolExecutor's internal
# queue is not designed to bound backlog, so the first version keeps **zero
# intentional backlog** instead of writing a custom executor for two shadow slots.
# Saturation drops; shadow telemetry may be dropped but must never harm production.
SHADOW_WORKERS = 2
SHADOW_CAPACITY = SHADOW_WORKERS
TELEMETRY_CAPACITY = 64

# Honest runtime limitation, kept machine-visible rather than only in prose: a
# worker that hangs indefinitely survives the caller's timeout, because a running
# Python thread cannot be safely killed. The outer budget bounds how long the
# caller waits; it does not bound worker termination. The durable snapshot read
# should therefore also be internally bounded where it can be.
KNOWN_RUNTIME_LIMITATION = (
    "indefinitely stuck worker may survive caller timeout; the outer budget bounds "
    "caller latency, not worker termination"
)

CALLER_COMPLETED = "completed"
CALLER_TIMED_OUT = "timed_out"
CALLER_FAILED = "failed"
CALLER_CANCELLED = "cancelled"
CALLER_REJECTED = "rejected"

_SHUTDOWN = object()
_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_capacity = threading.BoundedSemaphore(SHADOW_CAPACITY)


def _shared_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=SHADOW_WORKERS, thread_name_prefix="shadow-parity"
            )
        return _executor


def shadow_resource_state() -> dict[str, object]:
    """Observability for tests and diagnostics: bounded, by construction."""
    executor = _executor
    available = _capacity._value  # noqa: SLF001 - diagnostic only
    return {
        "max_workers": SHADOW_WORKERS,
        "live_threads": 0 if executor is None else len(getattr(executor, "_threads", ())),
        "capacity_total": SHADOW_CAPACITY,
        "capacity_available": available,
        # Outstanding work = tokens held by futures that have not finished, which
        # is the quantity admission is supposed to bound.
        "outstanding_work": SHADOW_CAPACITY - available,
        "intentional_backlog": 0,
        "known_runtime_limitation": KNOWN_RUNTIME_LIMITATION,
    }


@dataclass(frozen=True)
class ShadowOutcome:
    """What the shadow produced, or why it produced nothing. Never an exception."""

    status: str
    value: object | None = None
    reason: str = ""
    caller_status: str = ""
    worker_cancel_requested: bool = False
    worker_termination_known: bool = False

    @property
    def ok(self) -> bool:
        return self.status == SHADOW_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "caller_status": self.caller_status,
            "worker_cancel_requested": self.worker_cancel_requested,
            "worker_termination_known": self.worker_termination_known,
        }


def run_shadow_bounded(
    work: Callable[[], object],
    *,
    budget_seconds: float = DEFAULT_SHADOW_BUDGET_SECONDS,
    on_telemetry: Callable[[object], None] | None = None,
) -> ShadowOutcome:
    """Run shadow work under a hard budget and a bounded admission policy.

    Never queues, never blocks past the budget, and never raises a business
    failure. Process control signals (KeyboardInterrupt, SystemExit) are not
    treated as shadow errors and are allowed to propagate.
    """
    if budget_seconds <= 0:
        return ShadowOutcome(
            SHADOW_UNAVAILABLE, None, "budget_not_positive", CALLER_REJECTED
        )
    if not _capacity.acquire(blocking=False):
        # Saturated: reject immediately rather than queue. Queueing would merely
        # move the unbounded growth from threads to backlog.
        return ShadowOutcome(
            SHADOW_UNAVAILABLE, None, "capacity_exhausted", CALLER_REJECTED
        )

    # The admission token is bound to the **future's** real lifetime, not to the
    # caller's wait. Releasing it when the caller returns would let a stuck worker
    # keep its token returned, so subsequent submissions would pile up in the
    # executor's internal queue without bound.
    try:
        future = _shared_executor().submit(work)
    except BaseException:
        _capacity.release()
        raise
    future.add_done_callback(lambda _: _capacity.release())

    try:
        value = future.result(timeout=budget_seconds)
    except FutureTimeout:
        # uture.cancel() only cancels work that has not started. A running
        # thread cannot be safely killed, so we report the caller side honestly
        # instead of claiming the worker stopped. The token stays held until the
        # future actually finishes (or a queued future is cancelled, which fires
        # the done callback).
        requested = future.cancel()
        outcome = ShadowOutcome(
            SHADOW_UNAVAILABLE, None, "budget_exceeded", CALLER_TIMED_OUT,
            worker_cancel_requested=bool(requested),
            worker_termination_known=False,
        )
    except CancelledError:
        outcome = ShadowOutcome(
            SHADOW_ERROR, None, "isolated:cancelled", CALLER_CANCELLED,
            worker_termination_known=True,
        )
    except Exception as exc:  # noqa: BLE001 - business failure isolation
        outcome = ShadowOutcome(
            SHADOW_ERROR, None, type(exc).__name__, CALLER_FAILED,
            worker_termination_known=True,
        )
    else:
        outcome = ShadowOutcome(
            SHADOW_OK, value, "", CALLER_COMPLETED, worker_termination_known=True
        )

    if on_telemetry is not None and outcome.ok:
        try:
            on_telemetry(outcome.value)
        except Exception:  # noqa: BLE001 - telemetry may be dropped
            pass
    return outcome


class BestEffortTelemetry:
    """Bounded telemetry sink: drop on overload instead of growing a backlog.

    ``chat turn success + parity artifact missing`` is a legal state; the reverse
    - a parity artifact that can fail or roll back a turn - stays forbidden.
    """

    def __init__(self, sink: Any | None = None, *, capacity: int = TELEMETRY_CAPACITY) -> None:
        self._sink = sink
        self._queue: queue.Queue[object] = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._recorded = 0
        self._dropped = 0
        self._closed = False
        self._flusher = threading.Thread(
            target=self._drain, name="shadow-telemetry", daemon=True
        )
        self._flusher.start()

    @property
    def recorded(self) -> int:
        return self._recorded

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def record(self, observation: object) -> None:
        if self._closed:
            with self._lock:
                self._dropped += 1
            return
        try:
            self._queue.put_nowait(observation)
        except queue.Full:
            with self._lock:
                self._dropped += 1

    def _drain(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SHUTDOWN:
                return
            try:
                if self._sink is not None:
                    self._sink.record(item)
                    with self._lock:
                        self._recorded += 1
                else:
                    with self._lock:
                        self._dropped += 1
            except Exception:  # noqa: BLE001 - telemetry may be dropped
                with self._lock:
                    self._dropped += 1

    def flush(self, *, timeout: float = 1.0) -> bool:
        """Wait for the backlog to drain. Test/diagnostic helper only."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty():
                return True
            time.sleep(0.005)
        return self._queue.empty()

    def close(self, *, timeout: float = 1.0) -> None:
        self._closed = True
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except queue.Full:
            pass
        self._flusher.join(timeout=timeout)
