# -*- coding: utf-8 -*-
"""§143-SI: production-addressable, default-inert Crawl4AI specialist.

This module exposes the Crawl4AI browser backend to production **only** through an
explicit specialist invocation. It is deliberately *not* part of
``ACTIVE_READER_CHAIN`` (``native_http -> wigolo_http``): registering/activating
the specialist can never make the default reader select it.

Frozen contract (docs/PROJECT_STATUS.md §143.144-§143.145):

* identity is the stable ``CRAWL4AI_BROWSER``;
* lifecycle is production-owned but reuses the A3 bridge contract verbatim
  (persistent worker, persistent stdout reader, request_id correlation,
  late/stale response discard, bounded timeout + cancellation, post-timeout
  health, faithful shutdown);
* the isolated interpreter is configured explicitly (``CRAWL4AI_PYTHON``,
  absolute path). THERE IS NO discovery: no venv probing, no PATH search, no
  fallback to the host interpreter;
* fail-closed: disabled / missing config / missing path / start failure /
  health failure all mean ``unavailable`` with a recorded reason;
* lazy start + warm reuse: the worker starts on the first explicit invocation
  and is reused afterwards;
* crash / unexpected EOF fails the current invocation, tears the bridge down,
  and NEVER replays the current request; the next explicit invocation lazily
  starts a fresh worker;
* a timeout only abandons its own request (the A3 bridge keeps a healthy worker
  alive); it never mechanically restarts a healthy worker.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from src.web.research.chain_executor import ChainAttemptRequest
from src.web.research.crawl4ai_browser_executor import (
    ADVERTISED_CAPABILITIES,
    Crawl4AIBridge,
    Crawl4AIBrowserBackendExecutor,
    WorkerUnavailable,
)
from src.web.research.read_escalation import (
    TIER_BROWSER,
    charge_run_envelope,
    escalation_mode,
    ESCALATION_BROWSER,
)

#: Stable production identity for the specialist (never the ambiguous "browser").
CRAWL4AI_BROWSER = "crawl4ai_browser"

#: Gate A: may the specialist exist / be invoked at all. Independent from the
#: future P1 ``explicit_reader_hints_enabled`` gate (gate B).
SPECIALIST_ENABLED_ENV = "CRAWL4AI_SPECIALIST_ENABLED"
#: Absolute path to the isolated interpreter that owns the Crawl4AI dependency
#: surface. No directory, no discovery.
SPECIALIST_PYTHON_ENV = "CRAWL4AI_PYTHON"
DEFAULT_MAX_CHARS = 20000

STATUS_DISABLED = "disabled"
STATUS_PYTHON_NOT_CONFIGURED = "python_not_configured"
STATUS_PYTHON_NOT_ABSOLUTE = "python_not_absolute"
STATUS_PYTHON_MISSING = "python_missing"
STATUS_BROWSER_TIER_DISABLED = "browser_tier_disabled"
STATUS_READY = "ready"


class SpecialistUnavailable(RuntimeError):
    """The specialist may not be invoked (fail-closed)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def specialist_enabled() -> bool:
    return (os.getenv(SPECIALIST_ENABLED_ENV) or "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }


def configured_python() -> str:
    return (os.getenv(SPECIALIST_PYTHON_ENV) or "").strip()


def _validate_python(path: str) -> tuple[bool, str]:
    if not path:
        return False, STATUS_PYTHON_NOT_CONFIGURED
    if not Path(path).is_absolute():
        return False, STATUS_PYTHON_NOT_ABSOLUTE
    if not Path(path).is_file():
        return False, STATUS_PYTHON_MISSING
    if hasattr(os, "access") and not os.access(path, os.X_OK):
        return False, STATUS_PYTHON_MISSING
    return True, ""


def _config_status() -> tuple[bool, str]:
    """Gate + interpreter validation, no worker side effects."""

    if not specialist_enabled():
        return False, STATUS_DISABLED
    ok, reason = _validate_python(configured_python())
    if not ok:
        return False, reason
    if escalation_mode() != ESCALATION_BROWSER:
        return False, STATUS_BROWSER_TIER_DISABLED
    return True, ""


class _SpecialistManager:
    """Production-owned lifecycle for ONE reusable Crawl4AI worker."""

    def __init__(
        self,
        *,
        bridge_factory: Callable[[str], Any] | None = None,
        executor_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._bridge_factory = bridge_factory or (lambda python: Crawl4AIBridge(python=python))
        self._executor_factory = executor_factory or Crawl4AIBrowserBackendExecutor
        self._bridge: Crawl4AIBridge | None = None
        self._lock = threading.Lock()
        #: number of times a worker process was actually started (diagnostics)
        self.worker_starts = 0
        self.worker_resets = 0

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, Any]:
        config_ok, reason = _config_status()
        bridge = self._bridge
        ready = bool(bridge is not None and bridge.availability)
        return {
            "backend": CRAWL4AI_BROWSER,
            "enabled": specialist_enabled(),
            "config_ok": config_ok,
            "python_configured": bool(configured_python()),
            "worker_started": bridge is not None,
            "worker_ready": ready,
            "worker_starts": self.worker_starts,
            "reason": "" if config_ok else reason,
        }

    # --------------------------------------------------------------- lifecycle
    def _ensure_bridge(self) -> Crawl4AIBridge:
        config_ok, reason = _config_status()
        if not config_ok:
            raise SpecialistUnavailable(reason)
        with self._lock:
            bridge = self._bridge
            if bridge is not None and bridge.availability:
                return bridge
            if bridge is not None:
                # dead / half-dead bridge from a previous invocation: tear down
                self._teardown(bridge)
            python = configured_python()
            bridge = self._bridge_factory(python)
            try:
                bridge.start()
            except Exception as exc:  # noqa: BLE001 - start failure is fail-closed
                self._teardown(bridge)
                raise SpecialistUnavailable(
                    f"start_failed:{type(exc).__name__}"
                ) from exc
            self._bridge = bridge
            self.worker_starts += 1
            return bridge

    def _teardown(self, bridge: Crawl4AIBridge) -> None:
        try:
            bridge.stop()
        except Exception:  # noqa: BLE001 - teardown must never raise
            pass
        if self._bridge is bridge:
            self._bridge = None
        self.worker_resets += 1

    def _unavailable_provenance(self, reason: str, *, wall_ms: float = 0.0) -> dict[str, Any]:
        return {
            "requested_specialist": CRAWL4AI_BROWSER,
            "actual_backend": "",
            "specialist_available": False,
            "specialist_ready": False,
            "unavailable_reason": reason,
            "terminal_outcome": "",
            "fallback_used": False,
            "usable_content": False,
            "latency_ms": wall_ms,
            "result": None,
        }

    # ---------------------------------------------------------------- invoke
    def invoke(
        self,
        *,
        url: str,
        mode: str = "browser",
        max_chars: int = DEFAULT_MAX_CHARS,
        session_id: str | None = None,
        setup_url: str | None = None,
        delay_ms: int = 0,
        hard_seconds_left: Callable[[], float] | None = None,
        charge_envelope: Callable[[float], None] | None = None,
        candidate_id: str = "crawl4ai-specialist",
    ) -> dict[str, Any]:
        """Run ONE explicit specialist read. Never selected automatically."""

        started = time.perf_counter()
        try:
            bridge = self._ensure_bridge()
        except SpecialistUnavailable as exc:
            return self._unavailable_provenance(
                exc.reason, wall_ms=round((time.perf_counter() - started) * 1000.0, 1)
            )
        except Exception as exc:  # noqa: BLE001 - defensive fail-closed
            return self._unavailable_provenance(
                f"unexpected:{type(exc).__name__}",
                wall_ms=round((time.perf_counter() - started) * 1000.0, 1),
            )

        executor = self._executor_factory(
            bridge=bridge,
            mode=mode,
            max_chars=max_chars,
            session_id=session_id,
            delay_ms=delay_ms,
            hard_seconds_left=hard_seconds_left,
            charge_envelope=charge_envelope
            or (lambda ms: charge_run_envelope(ms, TIER_BROWSER)),
            name=CRAWL4AI_BROWSER,
        )
        # §143.34 session establishment is an explicit input, consumed here and
        # never invented by the specialist; its cost is inside the timing.
        if setup_url:
            try:
                bridge.request(
                    timeout_ms=20000,
                    url=setup_url,
                    mode=mode,
                    max_chars=max_chars,
                    session_id=session_id,
                    delay_ms=0,
                )
            except WorkerUnavailable:
                # setup failure is a bounded, invocation-local failure
                pass
        try:
            result = executor.execute(
                ChainAttemptRequest(
                    candidate_id=candidate_id,
                    url=url,
                    host="",
                    backend=CRAWL4AI_BROWSER,
                    chain_step=0,
                    outer_attempt_number=1,
                )
            )
        except WorkerUnavailable:
            # crash / EOF mid-invocation: fail closed, never replay
            self._teardown(bridge)
            return self._unavailable_provenance(
                "worker_crash", wall_ms=round((time.perf_counter() - started) * 1000.0, 1)
            )
        wall_ms = round((time.perf_counter() - started) * 1000.0, 1)

        # A dead worker after the call is expected (crash/EOF) -> reset so the
        # NEXT explicit invocation lazily starts fresh; this invocation is done.
        if not bridge.availability:
            self._teardown(bridge)

        return {
            "requested_specialist": CRAWL4AI_BROWSER,
            "actual_backend": str(getattr(result, "backend", "")),
            "specialist_available": True,
            "specialist_ready": True,
            "unavailable_reason": "",
            "terminal_outcome": str(getattr(result, "retrieval_state", "")),
            "fallback_used": False,
            "usable_content": bool(getattr(result, "usable_content", False)),
            "latency_ms": wall_ms,
            "result": result,
        }

    def reset(self) -> None:
        with self._lock:
            bridge = self._bridge
            if bridge is not None:
                self._teardown(bridge)

    def shutdown(self) -> None:
        self.reset()


_manager = _SpecialistManager()


def crawl4ai_specialist_status() -> dict[str, Any]:
    return _manager.status()


def invoke_crawl4ai_specialist(**kwargs: Any) -> dict[str, Any]:
    """The single production-addressable specialist entry point."""

    return _manager.invoke(**kwargs)


def reset_crawl4ai_specialist() -> None:
    """Test/rollback helper: drop the warm worker without touching routing."""

    _manager.reset()


def shutdown_crawl4ai_specialist() -> None:
    _manager.shutdown()


__all__ = [
    "ADVERTISED_CAPABILITIES",
    "CRAWL4AI_BROWSER",
    "SPECIALIST_ENABLED_ENV",
    "SPECIALIST_PYTHON_ENV",
    "SpecialistUnavailable",
    "configured_python",
    "crawl4ai_specialist_status",
    "invoke_crawl4ai_specialist",
    "reset_crawl4ai_specialist",
    "shutdown_crawl4ai_specialist",
    "specialist_enabled",
]
