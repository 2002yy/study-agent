"""Deep-3T: the durable, non-blocking Deep trigger.

The database facts are the queue, so this runner holds no authoritative state. It re-discovers
work every interval, on an immediate startup scan, and whenever the response path signals it.
That is what makes a lost wake, a crash or a worker restart harmless: the durable facts are
still there, and the next scan finds them.

The runner deliberately owns no integrity taxonomy. A callback that raises leaves durable state
untouched and the item is rediscovered later; turning an unknown failure into a durable blocked
state belongs to Deep-3, not here.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from src.repositories.deep_trigger_repository import (
    ARM,
    DeepTriggerItem,
    DeepTriggerRepository,
)

SCAN_INTERVAL_SECONDS = 15.0
ARM_BATCH = 8
PENDING_BATCH = 16
SHUTDOWN_JOIN_SECONDS = 1.0

_logger = logging.getLogger(__name__)


class DeepTriggerRunner:
    """One background worker; concurrency is fixed at 1 for background research v1."""

    def __init__(
        self,
        repository: DeepTriggerRepository,
        *,
        arm: Callable[[str, str], Any] | None = None,
        consume: Callable[[str, str], Any] | None = None,
        interval_seconds: float = SCAN_INTERVAL_SECONDS,
        arm_batch: int = ARM_BATCH,
        pending_batch: int = PENDING_BATCH,
        logger: logging.Logger | None = None,
    ):
        self.repository = repository
        self.arm = arm
        self.consume = consume
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.arm_batch = max(0, int(arm_batch))
        self.pending_batch = max(0, int(pending_batch))
        self.logger = logger or _logger
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # --- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        """Idempotent: a second start never creates a second worker."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._wake.clear()
            thread = threading.Thread(
                target=self._run, name="deep-trigger", daemon=True
            )
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        """Bounded shutdown: never waits out a 180s Deep call."""

        self._stop.set()
        self._wake.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=SHUTDOWN_JOIN_SECONDS)

    def wake(self) -> None:
        """Signal the worker. Never runs work inline and never blocks the caller."""

        self._wake.set()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    # --- worker --------------------------------------------------------------------

    def _run(self) -> None:
        # Immediate recovery scan: a restart must not wait out the first interval.
        self._safe_scan()
        while not self._stop.is_set():
            self._wake.wait(timeout=self.interval_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break
            self._safe_scan()

    def _safe_scan(self) -> None:
        try:
            self.scan_once()
        except Exception:  # pragma: no cover - defensive: the worker must survive
            self.logger.exception("deep trigger scan failed")

    def scan_once(self) -> int:
        """One scan: ARM first, then PENDING, so a fresh handoff is consumed immediately."""

        processed = 0
        for item in self.repository.discover(
            arm_limit=self.arm_batch, pending_limit=0
        ):
            if self._stop.is_set():
                return processed
            processed += 1
            if self._arm(item) != "prepared":
                # not_requested / blocked: nothing was prepared for this item this scan.
                continue
        for item in self.repository.discover(
            arm_limit=0, pending_limit=self.pending_batch
        ):
            if self._stop.is_set():
                return processed
            processed += 1
            self._consume(item)
        return processed

    def _arm(self, item: DeepTriggerItem) -> str:
        if self.arm is None:
            return ""
        try:
            outcome = self.arm(item.parent_turn_id, item.thread_id)
        except Exception:
            # Trigger layer owns no integrity taxonomy: leave durable state alone and retry later.
            self.logger.exception("deep trigger arm callback failed")
            return ""
        return str(getattr(outcome, "status", "") or "")

    def _consume(self, item: DeepTriggerItem) -> None:
        if self.consume is None:
            return
        try:
            self.consume(item.parent_turn_id, item.thread_id)
        except Exception:
            self.logger.exception("deep trigger consume callback failed")


def trigger_scan_interval() -> float:
    """The frozen v1 scan interval, for diagnostics and tests."""

    return SCAN_INTERVAL_SECONDS


__all__ = [
    "ARM",
    "ARM_BATCH",
    "PENDING_BATCH",
    "SCAN_INTERVAL_SECONDS",
    "SHUTDOWN_JOIN_SECONDS",
    "DeepTriggerItem",
    "DeepTriggerRunner",
    "trigger_scan_interval",
]
