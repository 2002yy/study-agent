"""§116 P2-A3-2c explicit ``crawl4ai`` browser backend executor.

Crawl4AI lives in its **own virtualenv** (~90 dependencies), so this executor
talks to a long-lived worker process over line-delimited JSON rather than
importing the library. The worker owns provider execution only; this module owns
the projection into a :class:`ChainStepResult`.

Shape (the only allowed one)::

    A2 router / scheduler
        -> Crawl4AIBrowserBackendExecutor        (this module)
        -> READY warm isolated worker            (separate venv)
        -> provider observation
        -> frozen honesty layer                  (browser_honesty)
        -> ChainStepResult

What it does not do: no routing, no candidate lifecycle, no Evidence/Support/
Gate, no second budget truth. It reuses ``wigolo_http_execution_plan`` for the
B2 guards and the **browser tier's own** run envelope.

Availability
------------

``availability`` is true only while the worker has announced ``READY``. Its
3.3-3.8s startup is operational cost and is never billed to a candidate; while
the worker is starting, restarting or unhealthy the backend reports unavailable
so the scheduler does not plan it.

Execution strategy
------------------

``mode`` selects the provider-native path for a capability the router **already
demanded** (``pdf`` -> PDF strategies, anything else -> the browser path). That
is backend implementation, not a second routing authority. Choosing *which*
mode belongs to the caller that knows the demand; this module never infers it
from the URL.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.web.research.browser_honesty import (
    honesty_outcome,
    rendered_content_judgement,
)
from src.web.research.chain_executor import ChainAttemptRequest, ChainStepResult
from src.web.research.failure_taxonomy import (
    SKIP_REASON_DISABLED,
    SKIP_REASON_INSUFFICIENT_WINDOW,
    SKIP_REASON_PREFLIGHT,
    UNKNOWN_STATE,
    classify,
    from_invocation_state,
    from_read_adequacy,
)
from src.web.research.read_adequacy import ADEQUATE_SHAPE, classify_reader_result
from src.web.research.read_escalation import (
    ESCALATION_BROWSER,
    TIER_BROWSER,
    escalation_mode,
    run_envelope_remaining_ms,
    wigolo_http_execution_plan,
)

CRAWL4AI_BACKEND = "crawl4ai"

#: The provider's own renderer lives behind an isolated interpreter.
DEFAULT_WORKER = Path(__file__).with_name("crawl4ai_worker.py")

#: Cancellation grace the worker applies after a deadline; the bridge waits a
#: little longer than that before declaring the worker unhealthy.
BRIDGE_READ_SLACK_MS = 2000

#: Capability this executor is allowed to advertise as a BrowserBackend role.
#: Provider truth is wider (it can also do plain HTTP), but advertising that
#: would let an ordinary transport failure escalate to an expensive browser.
ADVERTISED_CAPABILITIES: frozenset[str] = frozenset({"js_render", "pdf", "session"})


#: §125 spawn parity: the foreground probe runs the worker from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]


class WorkerUnavailable(RuntimeError):
    """The isolated provider worker is not READY."""


@dataclass
class Crawl4AIBridge:
    """Owns the isolated worker process; provider execution only."""

    python: str = ""
    worker: Path = DEFAULT_WORKER
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)
    #: request_id -> queue the persistent reader resolves; a caller timeout only
    #: abandons its own entry, never the pipe reader.
    _pending: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    _pending_lock: Any = field(default=None, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)
    startup_ms: float | None = field(default=None, init=False)
    cancel_grace_ms: int | None = field(default=None, init=False)
    restarts: int = field(default=0, init=False)
    late_responses: int = field(default=0, init=False)
    malformed_lines: int = field(default=0, init=False)
    reader_alive: bool = field(default=False, init=False)
    #: §124: created once in ``start()``, never lazily from two threads.
    _events: Any = field(default=None, init=False, repr=False)
    #: Last exception raised by the reader thread (empty when healthy).
    reader_error: str = field(default="", init=False)
    #: Diagnostics: lines seen by the reader at all.
    lines_seen: int = field(default=0, init=False)
    #: Small tail of worker stderr (debug only; the pipe is always drained).
    _stderr_tail: Any = field(default=None, init=False, repr=False)
    #: §125: exactly one stdin writer for this bridge's lifetime.
    _write_lock: Any = field(default=None, init=False, repr=False)
    #: The Popen parameters actually used (spawn-parity record).
    spawn_params: Any = field(default=None, init=False)

    def start(self, *, timeout_ms: float = 60000.0) -> None:
        if not self.python:
            raise WorkerUnavailable("no worker interpreter configured")
        self._proc = subprocess.Popen(
            [self.python, "-u", "-X", "utf8", str(self.worker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            # §125 spawn parity: the foreground probe runs with cwd=REPO_ROOT.
            # Recorded as a parity correction, not yet a proven root cause.
            cwd=str(REPO_ROOT),
        )
        self.spawn_params = {
            "argv": [self.python, "-u", "-X", "utf8", str(self.worker)],
            "cwd": str(REPO_ROOT),
            "text": True,
            "encoding": "utf-8",
            "bufsize": 1,
        }
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._events = queue.Queue()
        self._write_lock = threading.Lock()
        self.reader_error = ""
        self.lines_seen = 0
        self.reader_alive = True
        threading.Thread(target=self._pump, daemon=True).start()
        # §124: stderr MUST be drained. Crawl4AI logs steadily to stderr; with
        # an unread PIPE the worker eventually blocks on a stderr write and
        # never emits its stdout response (the flaky 'lines_seen=1' symptom).
        self._stderr_tail = []
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        hello = self._next(timeout_ms)
        if hello.get("event") != "READY":
            raise WorkerUnavailable(f"worker did not become ready: {hello}")
        self.startup_ms = hello.get("startup_ms")
        self.cancel_grace_ms = hello.get("cancel_grace_ms")

    def _drain_stderr(self) -> None:
        """Keep the worker's stderr pipe empty; retain a small tail for debug."""

        try:
            for line in self._proc.stderr:  # type: ignore[union-attr]
                if len(self._stderr_tail) < 200:
                    self._stderr_tail.append(line.rstrip())
        except Exception:
            pass

    def _pump(self) -> None:
        """The ONE stdout reader for this worker's lifetime.

        It parses each protocol line and hands it to the request that owns it.
        It is never cancelled by a caller timeout, so the pipe can never be read
        by two different readers racing for the same line.
        """

        try:
            for line in self._proc.stdout:  # type: ignore[union-attr]
                if not line.strip():
                    continue
                self.lines_seen += 1
                try:
                    payload = json.loads(line)
                except Exception:
                    self.malformed_lines += 1
                    continue
                request_id = str(payload.get("request_id") or "")
                if not request_id:
                    # READY / BYE / STATS style events
                    self._broadcast(payload)
                    continue
                with self._pending_lock:
                    box = self._pending.pop(request_id, None)
                if box is None:
                    # late response for an abandoned request: record and discard,
                    # never hand it to a later caller
                    self.late_responses += 1
                    continue
                box.put(payload)
        except Exception as exc:  # noqa: BLE001 - a dead reader must be visible
            self.reader_error = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            self.reader_alive = False
            self._fail_all_pending("worker_eof")

    def _broadcast(self, payload: dict[str, Any]) -> None:
        """Non-request events (READY/BYE/STATS) go to the shared inbox."""

        if self._events is not None:
            self._events.put(payload)

    def _fail_all_pending(self, reason: str) -> None:
        with self._pending_lock:
            boxes = list(self._pending.values())
            self._pending.clear()
        for box in boxes:
            box.put({"error": reason})

    def _next(self, timeout_ms: float) -> dict[str, Any]:
        if self._events is None:
            return {"error": "bridge_not_started"}
        try:
            return self._events.get(timeout=timeout_ms / 1000.0)
        except queue.Empty:
            return {"error": "bridge_read_timeout"}

    @property
    def ready(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def availability(self) -> bool:
        return self.ready

    def request(self, *, timeout_ms: float, **payload: Any) -> dict[str, Any]:
        if not self.ready:
            raise WorkerUnavailable("worker is not running")
        self._counter += 1
        request_id = f"r{self._counter}"
        box: Any = queue.Queue()
        with self._pending_lock:
            self._pending[request_id] = box
        payload["request_id"] = request_id
        # §135: timeout_ms is this method's own parameter, so it was never in
        # **payload and the worker silently fell back to its 30s default. The
        # request's explicit timeout must reach the worker's timeout authority.
        payload["timeout_ms"] = int(timeout_ms)
        line = json.dumps(payload) + "\n"
        try:
            with self._write_lock:
                self._proc.stdin.write(line)  # type: ignore[union-attr]
                self._proc.stdin.flush()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise WorkerUnavailable(f"write failed: {exc}") from exc
        try:
            return box.get(timeout=(timeout_ms + BRIDGE_READ_SLACK_MS) / 1000.0)
        except queue.Empty:
            # abandon only THIS request; the reader keeps the pipe and will
            # discard the late response by request_id
            with self._pending_lock:
                self._pending.pop(request_id, None)
            return {"error": "bridge_read_timeout", "request_id": request_id}

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")  # type: ignore[union-attr]
            self._proc.stdin.flush()  # type: ignore[union-attr]
            self._next(2000)
        except Exception:
            pass
        self._proc.terminate()
        self._proc = None
        self._fail_all_pending("worker_stopped")


def _skip_result(
    backend: str,
    *,
    state: str,
    skip_reason: str,
    detail: str,
    adequacy_reason: str = "",
    cost: Mapping[str, Any] | None = None,
) -> ChainStepResult:
    outcome = classify(
        backend=backend,
        raw_state=state,
        detail=detail,
        skip_reason=skip_reason,
        attempted=False,
    )
    return ChainStepResult(
        backend=backend,
        retrieval_state=outcome.state,
        attempted=False,
        usable_content=False,
        content="",
        adequacy_reason=adequacy_reason or detail,
        cost=dict(cost or {}),
        policy=outcome.to_policy_dict(),
    )


@dataclass
class Crawl4AIBrowserBackendExecutor:
    """One explicit ``crawl4ai`` attempt through the isolated worker."""

    bridge: Crawl4AIBridge | None = None
    #: Provider-native execution strategy for the *already demanded* capability.
    mode: str = "browser"
    max_chars: int = 0
    hard_seconds_left: Callable[[], float] | None = None
    charge_envelope: Callable[[float], None] | None = None
    mode_fn: Callable[[], str] | None = None
    envelope_tier: str = TIER_BROWSER
    session_id: str | None = None
    delay_ms: int = 0
    name: str = CRAWL4AI_BACKEND
    calls: int = field(default=0, init=False)

    def _escalation_mode(self) -> str:
        return escalation_mode()

    def _mode(self) -> str:
        return str(self.mode_fn()) if self.mode_fn is not None else str(self.mode)

    def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
        backend_name = self.name

        if self._escalation_mode() != ESCALATION_BROWSER:
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_DISABLED,
                detail="browser_tier_disabled",
            )
        if self.bridge is None or not self.bridge.availability:
            # startup / restarting / crashed: never plan a candidate on it
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_PREFLIGHT,
                detail="worker_unavailable",
            )

        plan = wigolo_http_execution_plan(
            hard_seconds_left=(
                self.hard_seconds_left() if self.hard_seconds_left else None
            ),
            envelope_remaining_ms=run_envelope_remaining_ms(self.envelope_tier),
        )
        if not plan.allowed:
            return _skip_result(
                backend_name,
                state="budget_exhausted",
                skip_reason=SKIP_REASON_INSUFFICIENT_WINDOW,
                detail=plan.deny_reason,
                adequacy_reason=plan.deny_reason,
                cost={
                    "deny_layer": plan.deny_layer,
                    "hard_headroom": plan.hard_headroom,
                    "envelope_remaining_ms": round(plan.envelope_remaining_ms, 1),
                    "effective_timeout_seconds": round(
                        plan.effective_timeout_seconds, 3
                    ),
                },
            )

        self.calls += 1
        deadline_ms = max(1, int(round(plan.effective_timeout_seconds * 1000.0)))
        started = time.perf_counter()
        try:
            observation = self.bridge.request(
                timeout_ms=deadline_ms,
                url=request.url,
                mode=self._mode(),
                max_chars=self.max_chars or 0,
                session_id=self.session_id,
                delay_ms=self.delay_ms,
            )
        except WorkerUnavailable as exc:
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_PREFLIGHT,
                detail=f"worker_unavailable:{type(exc).__name__}",
            )
        wall_ms = round((time.perf_counter() - started) * 1000.0, 1)
        self._charge(wall_ms)
        return self._project(observation, deadline_ms, wall_ms)

    def _charge(self, latency_ms: float) -> None:
        if self.charge_envelope is not None:
            self.charge_envelope(float(latency_ms))

    def _project(
        self, observation: Mapping[str, Any], deadline_ms: int, wall_ms: float
    ) -> ChainStepResult:
        backend_name = self.name
        cancellation = observation.get("cancellation") or {}
        content = str(observation.get("content") or "")
        provider_ok = bool(observation.get("provider_success"))
        provider_error = str(observation.get("error_message") or "")

        # §119 3: a bridge read timeout means the provider never produced an
        # observation. That is a bounded deadline failure, NOT invalid_content -
        # invalid_content claims "content was obtained and was inadequate".
        bridge_error = str(observation.get("error") or "")
        if bridge_error in {"bridge_read_timeout", "worker_eof", "empty_line"} or bridge_error.startswith("bad_json"):
            outcome = classify(
                backend=backend_name,
                raw_state="",
                detail="insufficient_remaining_window",
                skip_reason=SKIP_REASON_INSUFFICIENT_WINDOW,
                attempted=True,
            )
            return ChainStepResult(
                backend=backend_name,
                retrieval_state=outcome.state,
                attempted=True,
                usable_content=False,
                content="",
                adequacy_reason=f"bridge_failure:{bridge_error}",
                cost={
                    "latency_ms": wall_ms,
                    "fetch_ms": wall_ms,
                    "deadline_ms": deadline_ms,
                    "bridge_error": bridge_error,
                    "provider_state": "failure",
                },
                policy={
                    "attempted": True,
                    "skip_reason": "",
                    "breaker_state": "",
                    "backend": backend_name,
                },
            )

        # §115: a deadline that expired is a bounded failure, never a success.
        if observation.get("deadline_hit") or cancellation.get("provider_cancelled"):
            outcome = classify(
                backend=backend_name,
                raw_state="",
                detail="insufficient_remaining_window",
                skip_reason=SKIP_REASON_INSUFFICIENT_WINDOW,
                attempted=True,
            )
            return ChainStepResult(
                backend=backend_name,
                retrieval_state=outcome.state,
                attempted=True,
                usable_content=False,
                content="",
                adequacy_reason="deadline_expired",
                cost={
                    "latency_ms": wall_ms,
                    "fetch_ms": wall_ms,
                    "deadline_ms": deadline_ms,
                    "cancellation": dict(cancellation),
                    "provider_state": "failure",
                    "provider_error": provider_error[:200],
                },
                policy={
                    "attempted": True,
                    "skip_reason": "",
                    "breaker_state": "",
                    "backend": backend_name,
                },
            )

        payload = {"ok": provider_ok, "content": content, "url": ""}
        adequacy = classify_reader_result(payload)
        judgement = rendered_content_judgement(content) if content else ""

        if judgement:
            outcome = honesty_outcome(judgement, backend_name)
        elif content:
            outcome = from_read_adequacy(adequacy.shape, backend=backend_name)
        else:
            outcome = from_invocation_state(
                "empty",
                backend=backend_name,
                detail=provider_error or "empty_content",
            )

        usable = bool(
            content and adequacy.shape == ADEQUATE_SHAPE and not judgement
        )
        return ChainStepResult(
            backend=backend_name,
            retrieval_state=outcome.state,
            attempted=True,
            usable_content=usable,
            content=content if usable else "",
            adequacy_reason=judgement or adequacy.shape,
            cost={
                "latency_ms": wall_ms,
                "fetch_ms": wall_ms,
                "bytes": len(content.encode("utf-8")),
                "chars": len(content),
                "deadline_ms": deadline_ms,
                "cancellation": dict(cancellation),
                "mode": self._mode(),
                "provider_backend": CRAWL4AI_BACKEND,
                "provider_state": "success" if provider_ok else "failure",
                "provider_error": provider_error[:200],
                "canonical_retrieval_state": outcome.state,
                "honesty_downgrade": judgement,
            },
            policy={
                "attempted": True,
                "skip_reason": "",
                "breaker_state": "",
                "backend": backend_name,
            },
        )


def advertised_capabilities() -> Sequence[str]:
    return tuple(sorted(ADVERTISED_CAPABILITIES))


__all__ = [
    "ADVERTISED_CAPABILITIES",
    "BRIDGE_READ_SLACK_MS",
    "CRAWL4AI_BACKEND",
    "Crawl4AIBackendExecutor",
    "Crawl4AIBridge",
    "WorkerUnavailable",
    "advertised_capabilities",
]

#: Alias kept explicit so callers read the intent.
Crawl4AIBackendExecutor = Crawl4AIBrowserBackendExecutor
