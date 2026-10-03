"""§96 P2-A1a per-run health breaker and deadline preflight.

Goal, stated precisely: **without changing URL truth, Evidence Authority or retry
semantics, stop a ``(backend, host)`` that has already shown a stable failure
shape from repeatedly eating the research budget, and allow controlled probe
recovery.**

One authority, four states
--------------------------

::

    HealthKey = (backend, host)

    closed --qualifying failures >= threshold--> open
    open   --open_seconds elapsed--------------> half_open
    half_open --probe success------------------> closed (counters reset)
    half_open --probe qualifying failure-------> cooldown
    cooldown --cooldown_seconds elapsed--------> half_open (probe again)

``cooldown`` is a real state, not ``open`` plus a timestamp: only that keeps
provenance able to explain *why* a request was not sent.

Accounting
----------

Every failure goes through :func:`failure_taxonomy.counts_towards_health`. The
breaker never re-derives taxonomy itself, so:

* ``attempted=False`` never increases a failure streak;
* ``budget_exhausted`` says nothing about host health;
* ``not_found`` is URL truth, not backend sickness;
* content shapes (``invalid_content`` / ``shell_page`` / ``js_required``) are not
  network-health failures by default.

Cross-key isolation is deliberate: an open ``(native_http, bad.example)`` must not
touch ``(native_http, good.example)``, and ``(native_http, host)`` must not touch
``(browser, host)`` - that isolation is what lets A2 Progressive Reader fall back
correctly later.

Scope
-----

Per-run, in memory. Cross-run health caching is explicitly out of scope. This
module never switches backends, never changes a timeout, never touches retry
policy, and never writes evidence/support/gate.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.web.research.failure_taxonomy import (
    SKIP_REASON_CIRCUIT_OPEN,
    SKIP_REASON_INSUFFICIENT_WINDOW,
    BackendHealthPolicy,
    counts_towards_health,
    health_key,
)

READ_BREAKER_ENV = "RESEARCH_READ_BREAKER"
FAILURE_THRESHOLD_ENV = "RESEARCH_BREAKER_FAILURE_THRESHOLD"
OPEN_SECONDS_ENV = "RESEARCH_BREAKER_OPEN_SECONDS"
COOLDOWN_SECONDS_ENV = "RESEARCH_BREAKER_COOLDOWN_SECONDS"
HALF_OPEN_PROBES_ENV = "RESEARCH_BREAKER_HALF_OPEN_PROBES"

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"
STATE_COOLDOWN = "cooldown"

#: The primary reader used by the runtime read path.
NATIVE_HTTP_BACKEND = "native_http"

#: Sentinel host for a legacy, host-less mark. It lives *inside* the same state
#: model (one authority, just a broader key) rather than becoming a second one.
WILDCARD_HOST = "*"

TRANSITION_CLOSED_TO_OPEN = "failures_reached_threshold"
TRANSITION_OPEN_TO_HALF_OPEN = "open_window_elapsed"
TRANSITION_COOLDOWN_TO_HALF_OPEN = "cooldown_elapsed"
TRANSITION_PROBE_SUCCESS = "probe_succeeded"
TRANSITION_PROBE_FAILURE = "probe_failed"
TRANSITION_LEGACY_MARK = "legacy_mark_circuit_open"
TRANSITION_HEALTHY_OBSERVATION = "healthy_observation_reset"


def read_breaker_enabled() -> bool:
    """Diagnostic switch; **off by default** so A0/F2 baselines stay valid."""

    raw = (os.getenv(READ_BREAKER_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _env_float(name: str, fallback: float) -> float:
    raw = os.getenv(name)
    try:
        value = float(raw) if raw is not None and raw != "" else float(fallback)
    except (TypeError, ValueError):
        value = float(fallback)
    return max(0.0, value)


def _env_int(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(float(raw)) if raw is not None and raw != "" else int(fallback)
    except (TypeError, ValueError):
        value = int(fallback)
    return max(1, value)


def breaker_policy_from_env(
    base: BackendHealthPolicy | None = None,
) -> BackendHealthPolicy:
    """Frozen defaults, overridable for a harness. No magic numbers inline."""

    defaults = base or BackendHealthPolicy()
    return BackendHealthPolicy(
        failure_threshold=_env_int(
            FAILURE_THRESHOLD_ENV, defaults.failure_threshold
        ),
        open_seconds=_env_float(OPEN_SECONDS_ENV, defaults.open_seconds),
        half_open_probes=_env_int(
            HALF_OPEN_PROBES_ENV, defaults.half_open_probes
        ),
        cooldown_seconds=_env_float(
            COOLDOWN_SECONDS_ENV, defaults.cooldown_seconds
        ),
    )


@dataclass
class HealthRecord:
    """Per-key health state. Mutable by design; owned by one breaker instance."""

    key: str
    backend: str
    host: str
    state: str = STATE_CLOSED
    failure_streak: int = 0
    probe_index: int = 0
    probes_used: int = 0
    opened_at_ms: float | None = None
    eligible_probe_at_ms: float | None = None
    legacy: bool = False
    transitions: list[dict[str, Any]] = field(default_factory=list)

    def note(self, transition: str, *, now_ms: float, detail: str = "") -> None:
        self.transitions.append(
            {
                "transition": transition,
                "state": self.state,
                "at_ms": round(float(now_ms), 1),
                "failure_streak": int(self.failure_streak),
                "detail": detail[:120],
            }
        )
        del self.transitions[:-12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "health_key": self.key,
            "backend": self.backend,
            "host": self.host,
            "state": self.state,
            "failure_streak": int(self.failure_streak),
            "probe_index": int(self.probe_index),
            "probes_used": int(self.probes_used),
            "opened_at_ms": self.opened_at_ms,
            "eligible_probe_at_ms": self.eligible_probe_at_ms,
            "legacy": bool(self.legacy),
            "transitions": list(self.transitions),
        }


@dataclass(frozen=True)
class BreakerDecision:
    """What the breaker decided, plus everything needed to explain it later."""

    allowed: bool
    health_key: str
    backend: str
    host: str
    state_before: str
    state_after: str
    failure_streak: int
    probe_index: int
    is_probe: bool
    skip_reason: str
    eligible_probe_at_ms: float | None = None
    legacy: bool = False

    @property
    def attempted(self) -> bool:
        return bool(self.allowed)

    def to_policy_dict(self) -> dict[str, Any]:
        """The A0 four keys plus A1a provenance, for ``retrieval_policy``."""

        return {
            "attempted": bool(self.allowed),
            "skip_reason": self.skip_reason,
            "breaker_state": self.state_after,
            "backend": self.backend,
            "health_key": self.health_key,
            "breaker_state_before": self.state_before,
            "breaker_state_after": self.state_after,
            "failure_streak": int(self.failure_streak),
            "probe_index": int(self.probe_index),
            "is_probe": bool(self.is_probe),
            "eligible_probe_at_ms": self.eligible_probe_at_ms,
            "legacy": bool(self.legacy),
        }


@dataclass(frozen=True)
class DeadlineDecision:
    """Result of the pre-attempt window check (separate from the breaker)."""

    allowed: bool
    remaining_seconds: float
    required_seconds: float
    skip_reason: str = ""

    @property
    def attempted(self) -> bool:
        return bool(self.allowed)

    def to_policy_dict(self) -> dict[str, Any]:
        return {
            "attempted": bool(self.allowed),
            "skip_reason": self.skip_reason,
            "breaker_state": "",
            "backend": "",
            "remaining_seconds": round(float(self.remaining_seconds), 3),
            "required_seconds": round(float(self.required_seconds), 3),
        }


def deadline_preflight(
    *,
    remaining_seconds: float,
    timeout_seconds: float,
    reserve_seconds: float,
) -> DeadlineDecision:
    """Can the remaining research window still accommodate one attempt?

    Reuses the *existing* timeout and reserve; it introduces no latency
    estimator. A refusal is a policy skip and never feeds breaker health.
    """

    remaining = float(remaining_seconds)
    required = float(timeout_seconds) + float(reserve_seconds)
    allowed = remaining >= required
    return DeadlineDecision(
        allowed=allowed,
        remaining_seconds=remaining,
        required_seconds=required,
        skip_reason="" if allowed else SKIP_REASON_INSUFFICIENT_WINDOW,
    )


class PerRunBreaker:
    """Per-run ``(backend, host)`` health state machine (in memory only)."""

    def __init__(
        self,
        *,
        policy: BackendHealthPolicy | None = None,
        now_ms: Callable[[], float] | None = None,
    ) -> None:
        self.policy = policy or BackendHealthPolicy()
        self._now_ms = now_ms or (lambda: time.monotonic() * 1000.0)
        self._records: dict[str, HealthRecord] = {}
        self._enabled = True

    # ------------------------------------------------------------------ internals

    def _record(self, backend: str, host: str) -> HealthRecord:
        key = health_key(backend, host)
        record = self._records.get(key)
        if record is None:
            record = HealthRecord(key=key, backend=str(backend), host=str(host))
            self._records[key] = record
        return record

    def _advance(self, record: HealthRecord, now_ms: float) -> None:
        """Apply time-based transitions lazily (no timers, no background work)."""

        due = record.eligible_probe_at_ms
        if due is None or now_ms < float(due):
            return
        if record.state == STATE_OPEN:
            record.state = STATE_HALF_OPEN
            record.probes_used = 0
            record.probe_index += 1
            record.eligible_probe_at_ms = None
            record.note(TRANSITION_OPEN_TO_HALF_OPEN, now_ms=now_ms)
        elif record.state == STATE_COOLDOWN:
            record.state = STATE_HALF_OPEN
            record.probes_used = 0
            record.probe_index += 1
            record.eligible_probe_at_ms = None
            record.note(TRANSITION_COOLDOWN_TO_HALF_OPEN, now_ms=now_ms)

    def _active(self, backend: str, host: str) -> tuple[HealthRecord, bool]:
        """The exact key, or the backend's wildcard key when it is the one open.

        A legacy host-less mark must still be able to refuse, and it does so
        through the same model rather than a parallel flag.
        """

        exact = self._record(backend, host)
        if exact.state != STATE_CLOSED:
            return exact, False
        if str(host) == WILDCARD_HOST:
            return exact, False
        wildcard = self._records.get(health_key(backend, WILDCARD_HOST))
        if wildcard is not None and wildcard.state != STATE_CLOSED:
            return wildcard, True
        return exact, False

    # --------------------------------------------------------------------- public

    def allow(self, *, backend: str, host: str) -> BreakerDecision:
        """Decide whether one attempt may be sent, advancing time-based states."""

        now_ms = float(self._now_ms())
        record, via_wildcard = self._active(backend, host)
        self._advance(record, now_ms)
        state_before = record.state
        allowed = True
        is_probe = False
        skip_reason = ""
        if state_before == STATE_OPEN:
            allowed = False
            skip_reason = SKIP_REASON_CIRCUIT_OPEN
        elif state_before == STATE_COOLDOWN:
            allowed = False
            skip_reason = SKIP_REASON_CIRCUIT_OPEN
        elif state_before == STATE_HALF_OPEN:
            if record.probes_used >= int(self.policy.half_open_probes):
                allowed = False
                skip_reason = SKIP_REASON_CIRCUIT_OPEN
            else:
                is_probe = True
                record.probes_used += 1
        return BreakerDecision(
            allowed=allowed,
            health_key=record.key,
            backend=record.backend,
            host=record.host,
            state_before=state_before,
            state_after=record.state,
            failure_streak=int(record.failure_streak),
            probe_index=int(record.probe_index),
            is_probe=is_probe,
            skip_reason=skip_reason,
            eligible_probe_at_ms=record.eligible_probe_at_ms,
            legacy=bool(record.legacy or via_wildcard),
        )

    def record(
        self, *, backend: str, host: str, state: str, attempted: bool
    ) -> BreakerDecision:
        """Feed one observed outcome back into the state machine."""

        now_ms = float(self._now_ms())
        record, via_wildcard = self._active(backend, host)
        self._advance(record, now_ms)
        state_before = record.state
        counts = counts_towards_health(state, attempted=attempted)
        if not attempted:
            # A policy skip observed nothing; it can never move health.
            pass
        elif counts:
            record.failure_streak += 1
            if state_before == STATE_HALF_OPEN:
                record.state = STATE_COOLDOWN
                record.eligible_probe_at_ms = now_ms + float(
                    self.policy.cooldown_seconds
                ) * 1000.0
                record.note(TRANSITION_PROBE_FAILURE, now_ms=now_ms, detail=state)
            elif state_before == STATE_CLOSED and record.failure_streak >= int(
                self.policy.failure_threshold
            ):
                record.state = STATE_OPEN
                record.opened_at_ms = now_ms
                record.eligible_probe_at_ms = now_ms + float(
                    self.policy.open_seconds
                ) * 1000.0
                record.note(TRANSITION_CLOSED_TO_OPEN, now_ms=now_ms, detail=state)
        else:
            # A healthy observation (success, or a content judgement that proves
            # the exchange happened) clears the streak and closes a probe.
            if record.failure_streak or state_before != STATE_CLOSED:
                record.failure_streak = 0
                if state_before == STATE_HALF_OPEN:
                    record.state = STATE_CLOSED
                    record.eligible_probe_at_ms = None
                    record.note(TRANSITION_PROBE_SUCCESS, now_ms=now_ms, detail=state)
                else:
                    record.note(
                        TRANSITION_HEALTHY_OBSERVATION, now_ms=now_ms, detail=state
                    )
        return BreakerDecision(
            allowed=state_before in (STATE_CLOSED, STATE_HALF_OPEN),
            health_key=record.key,
            backend=record.backend,
            host=record.host,
            state_before=state_before,
            state_after=record.state,
            failure_streak=int(record.failure_streak),
            probe_index=int(record.probe_index),
            is_probe=False,
            skip_reason="",
            eligible_probe_at_ms=record.eligible_probe_at_ms,
            legacy=bool(record.legacy or via_wildcard),
        )

    def mark_open(
        self, *, backend: str, host: str = WILDCARD_HOST, legacy: bool = True
    ) -> BreakerDecision:
        """Compatibility shell for the legacy ``mark_circuit_open()``.

        With no host the mark lands on the backend's wildcard key - still one
        authority, just a broader key - and is flagged ``legacy`` so provenance
        can tell the two apart.
        """

        now_ms = float(self._now_ms())
        record = self._record(backend, host)
        record.state = STATE_OPEN
        record.opened_at_ms = now_ms
        record.eligible_probe_at_ms = now_ms + float(self.policy.open_seconds) * 1000.0
        record.legacy = bool(legacy)
        record.note(TRANSITION_LEGACY_MARK, now_ms=now_ms)
        return BreakerDecision(
            allowed=False,
            health_key=record.key,
            backend=record.backend,
            host=record.host,
            state_before=STATE_OPEN,
            state_after=STATE_OPEN,
            failure_streak=int(record.failure_streak),
            probe_index=int(record.probe_index),
            is_probe=False,
            skip_reason=SKIP_REASON_CIRCUIT_OPEN,
            eligible_probe_at_ms=record.eligible_probe_at_ms,
            legacy=True,
        )

    def snapshot(self) -> list[dict[str, Any]]:
        """Bounded provenance for the run metrics (never a second ledger)."""

        return [record.to_dict() for record in self._records.values()]

    def state_for(self, *, backend: str, host: str) -> str:
        """Current state without advancing it (diagnostics only)."""

        record, _ = self._active(backend, host)
        return record.state


def host_of(url: str) -> str:
    """Host part of a URL, for the health key (no URL rewriting)."""

    text = str(url or "").strip()
    if not text:
        return ""
    if "//" in text:
        text = text.split("//", 1)[1]
    return text.split("/", 1)[0].split("?", 1)[0].lower()


__all__ = [
    "COOLDOWN_SECONDS_ENV",
    "DeadlineDecision",
    "FAILURE_THRESHOLD_ENV",
    "HALF_OPEN_PROBES_ENV",
    "NATIVE_HTTP_BACKEND",
    "OPEN_SECONDS_ENV",
    "READ_BREAKER_ENV",
    "STATE_CLOSED",
    "STATE_COOLDOWN",
    "STATE_HALF_OPEN",
    "STATE_OPEN",
    "WILDCARD_HOST",
    "BreakerDecision",
    "HealthRecord",
    "PerRunBreaker",
    "breaker_policy_from_env",
    "deadline_preflight",
    "host_of",
    "read_breaker_enabled",
]
