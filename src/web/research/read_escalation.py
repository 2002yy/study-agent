"""Wigolo HTTP capability switches and bounded run-envelope budget policy.

The production reader chain runs native_http before the explicit wigolo_http
executor. This module owns the HTTP/browser tier ledger and the single
execution-time Wigolo budget plan; it does not perform retrievals or create
evidence. The old in-reader hidden escalation path has been retired.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


ESCALATION_ENV = "RESEARCH_WIGOLO_ESCALATION"
BROWSER_TIER_ENV = "WIGOLO_BROWSER_ESCALATION"

# §71B2 FROZEN budget parameters (3.0s each), with separate semantics even
# though the values coincide:
#   - the hard-headroom gate asks "is an optional external retrieval still
#     worth starting?" given what is left of the run;
#   - the per-run envelope caps how much wall clock this optional fallback may
#     consume across the whole run, so repeated inadequate reads cannot
#     accumulate into a budget breach.
# Neither is a call-count cap: B1 showed failures cost 31-79ms, so refusing the
# third attempt by count could reject a 40ms rescue for no reason.
#
# Evidence for 3.0s: measured cold HTTP on a healthy host ~1.0s (same-host
# control fetch), historical cold 0.7-1.5s, warm/cache 15-80ms, worst observed
# attempt now truncates at 3.03s (was 8.03s before the effective-timeout fix),
# and useful rescues concentrate in the first one or two attempts. B2's own
# scope is bounding this fallback - it does NOT own the run's 60s budget (that
# long tail belongs to the wave/selector/admission distribution, see F2).
HTTP_MIN_HARD_SECONDS_ENV = "RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT"
HTTP_RUN_ENVELOPE_ENV = "RESEARCH_WIGOLO_HTTP_RUN_ENVELOPE_SECONDS"
HTTP_MIN_HARD_SECONDS_DEFAULT = 3.0  # FROZEN
HTTP_RUN_ENVELOPE_DEFAULT = 3.0  # FROZEN
# A request is not started unless it plausibly fits: an envelope with 0.4s left
# must not launch a call that usually takes ~1s and then discover the breach.
EFFECTIVE_TIMEOUT_FLOOR_SECONDS = 1.0

# Execution tiers. Declared here because the envelope ledger is keyed by tier.
ESCALATION_OFF = "off"
ESCALATION_HTTP = "http"
ESCALATION_BROWSER = "browser"
TIER_HTTP = "http"
TIER_BROWSER = "browser"

# §111 A3-1R: HTTP and browser have independent per-run envelopes.
# A process-global dict let one research run erase another run's spent time on
# reset. ContextVar isolates concurrent threads/async tasks without changing
# call sites or the frozen 3.0s tier budgets. Updates are copy-on-write so
# contexts inherited by sibling asyncio tasks cannot mutate the same dict.
# The application run still owns the *global* research_seconds_left deadline.
_RUN_ENVELOPE: ContextVar[dict[str, float] | None] = ContextVar(
    "research_run_envelope", default=None
)


def _envelope_key(tier: str) -> str:
    key = str(tier or TIER_HTTP).strip().lower()
    return key if key in (TIER_HTTP, TIER_BROWSER) else TIER_HTTP


def reset_run_envelope(tier: str = TIER_HTTP) -> None:
    """Reset one tier for the current execution context, not the process."""

    ledger = dict(_RUN_ENVELOPE.get() or {})
    ledger[_envelope_key(tier)] = 0.0
    _RUN_ENVELOPE.set(ledger)


def run_envelope_spent_ms(tier: str = TIER_HTTP) -> float:
    ledger = _RUN_ENVELOPE.get()
    return round((ledger or {}).get(_envelope_key(tier), 0.0), 1)


def run_envelope_remaining_ms(tier: str = TIER_HTTP) -> float:
    return round(
        max(0.0, http_run_envelope_seconds() * 1000.0 - run_envelope_spent_ms(tier)),
        1,
    )


def charge_run_envelope(latency_ms: float, tier: str = TIER_HTTP) -> None:
    """Charge the actual attempt cost only to the current execution context."""

    key = _envelope_key(tier)
    ledger = dict(_RUN_ENVELOPE.get() or {})
    ledger[key] = round(ledger.get(key, 0.0) + max(0.0, float(latency_ms)), 1)
    _RUN_ENVELOPE.set(ledger)


def http_min_hard_seconds() -> float:
    """Frozen default 3.0; the env override exists for experiments only."""

    raw = os.getenv(HTTP_MIN_HARD_SECONDS_ENV)
    try:
        value = float(raw) if raw is not None and raw != "" else HTTP_MIN_HARD_SECONDS_DEFAULT
    except (TypeError, ValueError):
        value = HTTP_MIN_HARD_SECONDS_DEFAULT
    return max(0.0, min(value, 120.0))


def http_run_envelope_seconds() -> float:
    """Frozen default 3.0; the env override exists for experiments only."""

    raw = os.getenv(HTTP_RUN_ENVELOPE_ENV)
    try:
        value = float(raw) if raw is not None and raw != "" else HTTP_RUN_ENVELOPE_DEFAULT
    except (TypeError, ValueError):
        value = HTTP_RUN_ENVELOPE_DEFAULT
    return max(0.0, min(value, 120.0))


def escalation_mode() -> str:
    """``off`` (default) | ``http`` | ``browser`` (experimental)."""

    raw = (os.getenv(ESCALATION_ENV) or "").strip().lower()
    if raw in {"browser", "http+browser"}:
        return ESCALATION_BROWSER
    if raw in {"1", "true", "on", "yes", "http"}:
        return ESCALATION_HTTP
    return ESCALATION_OFF


def browser_tier_allowed() -> bool:
    """The browser tier is opt-in twice: mode *and* its own flag."""

    if escalation_mode() != ESCALATION_BROWSER:
        return False
    raw = (os.getenv(BROWSER_TIER_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


@dataclass(frozen=True)
class WigoloHttpExecutionPlan:
    """§103 A2d-3: the one budget truth for a Wigolo HTTP attempt.

    Consumed by the explicit ``wigolo_http`` chain executor. The plan
    provides the single execution-time budget verdict and answers the three
    B2 questions, in order:

    1. is there enough remaining *hard* budget (``MIN_HARD_SECONDS_LEFT``)?
    2. is there per-run envelope left?
    3. what timeout may this single call actually use?

    It decides nothing else: no mode check, no adequacy check, no preflight, no
    network. Those stay with the caller.
    """

    allowed: bool
    deny_reason: str
    #: Which B2 layer refused: ``hard_headroom`` | ``envelope`` |
    #: ``effective_timeout`` | ``""``. The explicit executor maps refusals
    #: to ``budget_exhausted`` without performing a provider call.
    deny_layer: str
    hard_headroom: float | None
    min_hard_seconds: float
    envelope_remaining_ms: float
    effective_timeout_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "deny_reason": self.deny_reason,
            "deny_layer": self.deny_layer,
            "hard_headroom": self.hard_headroom,
            "min_hard_seconds": self.min_hard_seconds,
            "envelope_remaining_ms": round(float(self.envelope_remaining_ms), 1),
            "effective_timeout_seconds": round(
                float(self.effective_timeout_seconds), 3
            ),
        }


def wigolo_http_execution_plan(
    *,
    hard_seconds_left: float | None,
    envelope_remaining_ms: float | None = None,
    min_hard_seconds: float | None = None,
) -> WigoloHttpExecutionPlan:
    """Compute the B2 verdict for one Wigolo HTTP attempt.

    Refusal reasons remain frozen: ``hard_headroom_insufficient`` then
    ``run_envelope_exhausted``, with the same effective-timeout floor.
    """

    headroom: float | None = (
        None if hard_seconds_left is None else float(hard_seconds_left)
    )
    min_hard = (
        http_min_hard_seconds()
        if min_hard_seconds is None
        else float(min_hard_seconds)
    )
    envelope = (
        run_envelope_remaining_ms(TIER_HTTP)
        if envelope_remaining_ms is None
        else float(envelope_remaining_ms)
    )

    def plan(
        allowed: bool, reason: str, layer: str, effective: float
    ) -> WigoloHttpExecutionPlan:
        return WigoloHttpExecutionPlan(
            allowed=allowed,
            deny_reason=reason,
            deny_layer=layer,
            hard_headroom=headroom,
            min_hard_seconds=min_hard,
            envelope_remaining_ms=envelope,
            effective_timeout_seconds=effective,
        )

    if headroom is not None and headroom < min_hard:
        return plan(False, "hard_headroom_insufficient", "hard_headroom", 0.0)
    if envelope <= 0:
        return plan(False, "run_envelope_exhausted", "envelope", 0.0)
    effective_timeout = (
        min(envelope / 1000.0, headroom) if headroom is not None else envelope / 1000.0
    )
    if effective_timeout < EFFECTIVE_TIMEOUT_FLOOR_SECONDS:
        if headroom is not None and headroom < EFFECTIVE_TIMEOUT_FLOOR_SECONDS:
            return plan(
                False,
                "hard_headroom_insufficient",
                "effective_timeout",
                effective_timeout,
            )
        return plan(
            False, "run_envelope_exhausted", "effective_timeout", effective_timeout
        )
    return plan(True, "", "", effective_timeout)


__all__ = [
    "BROWSER_TIER_ENV",
    "ESCALATION_BROWSER",
    "ESCALATION_ENV",
    "ESCALATION_HTTP",
    "ESCALATION_OFF",
    "TIER_BROWSER",
    "TIER_HTTP",
    "browser_tier_allowed",
    "escalation_mode",
]
