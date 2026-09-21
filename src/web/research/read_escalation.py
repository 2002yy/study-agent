"""§71C-3a reader escalation: current reader first, Wigolo HTTP only on FAIL.

Production policy (frozen in §78):

    current reader -> ReadAdequacy PASS -> existing pipeline
                   -> FAIL -> wigolo http tier -> ReadAdequacy PASS -> pipeline
                                                 FAIL -> stop (browser is not
                                                         automatic)

Hard rules:

* the current reader always runs first and its result is never modified by a
  failed escalation - a fallback that breaks only loses its own chance;
* nothing here creates evidence: the escalated text goes back through the same
  extraction / support / Gate path as any other read;
* every external attempt is a terminal retrieval invocation with its tier
  recorded (``http`` | ``browser``), and the adequacy transition is logged;
* the browser tier is off unless the experiment flag explicitly asks for it.

The module is deliberately free of run-context state: callers pass a
``metrics_provider`` callable and the §71B ledger helpers re-resolve it at each
boundary (the §71A-1 lesson).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping

from src.web.research.read_adequacy import ADEQUATE_SHAPE, classify_reader_result
from src.web.research.retrieval_backends import (
    READ_OPERATION,
    TERMINAL_RETRIEVAL_STATES,
    RawReadArtifact,
    ReadRequest,
    create_retrieval_invocation,
    finalize_retrieval_invocation,
    retrieval_attempt_row,
)

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

# Per-run spent ledger (scalars only, per the §71A-1 rule); reset at run start.
_HTTP_ENVELOPE: dict[str, float] = {"wigolo_http_spent_ms": 0.0}


def http_min_hard_seconds() -> float:
    """Frozen default 3.0; the env override exists for experiments only."""

    raw = os.getenv(HTTP_MIN_HARD_SECONDS_ENV)
    try:
        value = float(raw) if raw not in (None, "") else HTTP_MIN_HARD_SECONDS_DEFAULT
    except (TypeError, ValueError):
        value = HTTP_MIN_HARD_SECONDS_DEFAULT
    return max(0.0, min(value, 120.0))


def http_run_envelope_seconds() -> float:
    """Frozen default 3.0; the env override exists for experiments only."""

    raw = os.getenv(HTTP_RUN_ENVELOPE_ENV)
    try:
        value = float(raw) if raw not in (None, "") else HTTP_RUN_ENVELOPE_DEFAULT
    except (TypeError, ValueError):
        value = HTTP_RUN_ENVELOPE_DEFAULT
    return max(0.0, min(value, 120.0))


def reset_http_envelope() -> None:
    """Called once per run so the envelope is per-run, not per-process."""

    _HTTP_ENVELOPE["wigolo_http_spent_ms"] = 0.0


def http_envelope_spent_ms() -> float:
    return round(_HTTP_ENVELOPE["wigolo_http_spent_ms"], 1)


def http_envelope_remaining_ms() -> float:
    return round(
        max(0.0, http_run_envelope_seconds() * 1000.0 - _HTTP_ENVELOPE["wigolo_http_spent_ms"]),
        1,
    )


def charge_http_envelope(latency_ms: float) -> None:
    """Charge the *actual* cost of one attempt (success or failure)."""

    _HTTP_ENVELOPE["wigolo_http_spent_ms"] = round(
        _HTTP_ENVELOPE["wigolo_http_spent_ms"] + max(0.0, float(latency_ms)), 1
    )
ESCALATION_OFF = "off"
ESCALATION_HTTP = "http"
ESCALATION_BROWSER = "browser"
TIER_HTTP = "http"
TIER_BROWSER = "browser"


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


@dataclass
class EscalationOutcome:
    """Diagnostics for one escalation decision (never changes evidence)."""

    attempted: bool = False
    tier: str = ""
    state: str = ""
    reason: str = ""
    shape_before: str = ""
    shape_after: str = ""
    chars_before: int = 0
    chars_after: int = 0
    latency_ms: float = 0.0
    cache_hit: bool | None = None
    retrieval_mode: str = ""
    max_chars_requested: int = 0
    preflight: str = ""
    # §71B/B1 instrumentation: where and when the escalation happened
    url: str = ""
    attempt_seq: int = 0
    research_seconds_left_at_start: float | None = None
    hard_seconds_left_at_start: float | None = None
    envelope_remaining_at_start_ms: float | None = None
    effective_timeout_seconds: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rescued(self) -> bool:
        return self.shape_after == ADEQUATE_SHAPE and self.shape_before != ADEQUATE_SHAPE

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "attempted": self.attempted,
            "tier": self.tier,
            "state": self.state,
            "reason": self.reason,
            "shape_before": self.shape_before,
            "shape_after": self.shape_after,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "retrieval_mode": self.retrieval_mode,
            "max_chars_requested": self.max_chars_requested,
            "preflight": self.preflight,
            "rescued": self.rescued,
            "url": self.url,
            "attempt_seq": self.attempt_seq,
            "research_seconds_left_at_start": self.research_seconds_left_at_start,
            "hard_seconds_left_at_start": self.hard_seconds_left_at_start,
            "envelope_remaining_at_start_ms": self.envelope_remaining_at_start_ms,
            "effective_timeout_seconds": self.effective_timeout_seconds,
        }
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload




def _resolve_headroom(value: Any) -> float | None:
    """Headroom fields may be callables (runtime closure) or plain values."""

    if value is None:
        return None
    try:
        number = float(value() if callable(value) else value)
        return round(number, 3)
    except Exception:
        return None

def escalate_read(
    *,
    url: str,
    current: Mapping[str, Any] | None,
    http_backend: Any | None,
    metrics_provider: Callable[[], MutableMapping[str, Any] | None] | None = None,
    claim_id: str = "",
    wave_index: int = 0,
    max_chars: int = 0,
    backend_factory: Callable[[str], Any] | None = None,
    attempt_seq: int = 0,
    research_seconds_left: Callable[[], float] | None = None,
    hard_seconds_left: Callable[[], float] | None = None,
) -> tuple[Mapping[str, Any] | None, EscalationOutcome]:
    """Try one escalation for an inadequate read.

    Returns ``(result, outcome)`` where ``result`` is the current reader's
    payload unless the escalation produced adequate content. Any failure leaves
    the original payload untouched and is recorded as a terminal retrieval
    failure.
    """

    outcome = EscalationOutcome(
        url=str(url or ""),
        attempt_seq=int(attempt_seq or 0),
        research_seconds_left_at_start=_resolve_headroom(research_seconds_left),
        hard_seconds_left_at_start=_resolve_headroom(hard_seconds_left),
        shape_before=classify_reader_result(current).shape,
        chars_before=classify_reader_result(current).chars,
        max_chars_requested=int(max_chars or 0),
    )
    mode = escalation_mode()
    if mode == ESCALATION_OFF:
        outcome.reason = "disabled"
        return current, outcome
    if classify_reader_result(current).adequate:
        # never escalate an adequate read (already-PASS pages must not call out)
        outcome.reason = "already_adequate"
        return current, outcome

    # §71B2 two-layer admission, evaluated with the live scalars:
    hard_headroom = _resolve_headroom(hard_seconds_left)
    min_hard = http_min_hard_seconds()
    if hard_headroom is not None and hard_headroom < min_hard:
        outcome.reason = "hard_headroom_insufficient"
        outcome.state = "unsupported"
        _record_attempt(
            metrics_provider,
            outcome,
            claim_id=claim_id,
            wave_index=wave_index,
            backend_name="wigolo",
            state="skipped_no_budget",
            result_count=0,
            bytes_=0,
        )
        return current, outcome
    envelope_remaining = http_envelope_remaining_ms()
    outcome.envelope_remaining_at_start_ms = envelope_remaining
    if envelope_remaining <= 0:
        outcome.reason = "run_envelope_exhausted"
        outcome.state = "skipped_no_budget"
        _record_attempt(
            metrics_provider,
            outcome,
            claim_id=claim_id,
            wave_index=wave_index,
            backend_name="wigolo",
            state="skipped_no_budget",
            result_count=0,
            bytes_=0,
        )
        return current, outcome
    # effective timeout: one call must not punch through the envelope or the
    # remaining hard budget (B2: the envelope is executable, not descriptive).
    effective_timeout = min(envelope_remaining / 1000.0, hard_headroom) if (
        hard_headroom is not None
    ) else envelope_remaining / 1000.0
    if effective_timeout < EFFECTIVE_TIMEOUT_FLOOR_SECONDS:
        outcome.reason = (
            "hard_headroom_insufficient"
            if hard_headroom is not None and hard_headroom < EFFECTIVE_TIMEOUT_FLOOR_SECONDS
            else "run_envelope_exhausted"
        )
        outcome.state = "skipped_no_budget"
        outcome.effective_timeout_seconds = round(effective_timeout, 3)
        _record_attempt(
            metrics_provider,
            outcome,
            claim_id=claim_id,
            wave_index=wave_index,
            backend_name="wigolo",
            state="skipped_no_budget",
            result_count=0,
            bytes_=0,
        )
        return current, outcome
    outcome.effective_timeout_seconds = round(effective_timeout, 3)

    backend = http_backend if http_backend is not None else (
        backend_factory(TIER_HTTP) if backend_factory is not None else None
    )
    if backend is None:
        outcome.reason = "backend_unavailable"
        return current, outcome

    preflight = getattr(backend, "preflight", None)
    if callable(preflight):
        status = str(preflight() or "")
        outcome.preflight = status
        if status != "ready":
            # fail closed: an unavailable or misconfigured daemon must never be
            # "tried anyway" - the current read continues untouched.
            outcome.reason = (
                "backend_unavailable" if status == "unavailable" else "misconfigured"
            )
            outcome.state = "unsupported"
            _record_attempt(
                metrics_provider,
                outcome,
                claim_id=claim_id,
                wave_index=wave_index,
                backend_name=str(getattr(backend, "name", "wigolo")),
                state="unsupported",
                result_count=0,
                bytes_=0,
            )
            return current, outcome

    outcome.attempted = True
    outcome.tier = TIER_HTTP
    fetched: RawReadArtifact | None = None
    try:
        fetched = backend.fetch(
            ReadRequest(
                url=url,
                max_chars=max_chars or 0,
                timeout_seconds=round(outcome.effective_timeout_seconds, 3)
                if outcome.effective_timeout_seconds
                else None,
            )
        )
    except Exception as exc:  # noqa: BLE001 - shadow/fallback must never raise
        outcome.state = "transport_error"
        outcome.reason = f"{type(exc).__name__}"
        charge_http_envelope(outcome.latency_ms)
        _record_attempt(
            metrics_provider,
            outcome,
            claim_id=claim_id,
            wave_index=wave_index,
            backend_name=str(getattr(backend, "name", "wigolo")),
            state="transport_error",
            result_count=0,
            bytes_=0,
        )
        return current, outcome

    if fetched is None:
        outcome.reason = "no_artifact"
        return current, outcome
    artifact = fetched
    charge_http_envelope(artifact.latency_ms)
    failure_state = str((artifact.external_metadata or {}).get("state") or "")
    # §78.2-1: provenance must carry the value the daemon actually received (the
    # frozen contract value), not the caller's read-window slice.
    effective_max_chars = (artifact.external_metadata or {}).get("max_chars_requested")
    if isinstance(effective_max_chars, (int, float)) and effective_max_chars > 0:
        outcome.max_chars_requested = int(effective_max_chars)
    outcome.latency_ms = float(artifact.latency_ms)
    outcome.cache_hit = artifact.cache_hit
    outcome.retrieval_mode = artifact.retrieval_mode
    outcome.chars_after = len(artifact.content or "")
    escalated_payload = {
        "ok": artifact.usable,
        "content": artifact.content,
        "title": str((artifact.external_metadata or {}).get("title") or ""),
        "url": artifact.url or url,
        "method": artifact.retrieval_mode,
        "backend": artifact.backend,
    }
    outcome.shape_after = classify_reader_result(escalated_payload).shape
    outcome.state = failure_state or ("ok" if artifact.usable else "empty")
    if not artifact.usable:
        outcome.reason = failure_state or "empty_content"
    _record_attempt(
        metrics_provider,
        outcome,
        claim_id=claim_id,
        wave_index=wave_index,
        backend_name=str(artifact.backend or getattr(backend, "name", "wigolo")),
        state=outcome.state or "empty",
        result_count=1 if artifact.usable else 0,
        bytes_=int(artifact.bytes or 0),
    )
    if artifact.usable and outcome.shape_after == ADEQUATE_SHAPE:
        return escalated_payload, outcome
    # inadequate escalation: keep the original read untouched
    outcome.reason = outcome.reason or "still_inadequate"
    return current, outcome


def _record_attempt(
    metrics_provider: Callable[[], MutableMapping[str, Any] | None] | None,
    outcome: EscalationOutcome,
    *,
    claim_id: str,
    wave_index: int,
    backend_name: str,
    state: str,
    result_count: int,
    bytes_: int,
) -> None:
    """Ledger: one retrieval attempt + one terminal invocation, tier included."""

    if metrics_provider is None:
        return
    try:
        metrics = metrics_provider()
    except Exception:
        return
    if not isinstance(metrics, MutableMapping):
        return
    rows = metrics.get("retrieval_attempts")
    if not isinstance(rows, list):
        rows = []
    rows.append(
        retrieval_attempt_row(
            backend=backend_name,
            operation=READ_OPERATION,
            claim_id=claim_id,
            wave_index=wave_index,
            latency_ms=outcome.latency_ms,
            result_count=result_count,
            bytes=bytes_,
            cache_hit=bool(outcome.cache_hit),
            escalation_reason=outcome.reason,
        )
        | {
            "tier": outcome.tier or TIER_HTTP,
            "transition": _transition(outcome),
            "preflight": outcome.preflight,
            "state": outcome.state,
            "max_chars_requested": outcome.max_chars_requested,
        }
    )
    metrics["retrieval_attempts"] = rows[-60:]

    entry = create_retrieval_invocation(
        metrics_provider,
        claim_id=claim_id or "unknown",
        wave_index=wave_index,
        backend=backend_name,
        operation="fetch",
    )
    entry["tier"] = outcome.tier or TIER_HTTP
    finalize_retrieval_invocation(
        metrics_provider,
        entry,
        state=state if state in TERMINAL_RETRIEVAL_STATES else "empty",
        result_count=result_count,
        bytes=bytes_,
        cache_hit=bool(outcome.cache_hit),
        escalation_reason=outcome.reason,
        latency_ms=outcome.latency_ms,
    )


def _transition(outcome: EscalationOutcome) -> str:
    before = outcome.shape_before or "unknown"
    after = outcome.shape_after or before
    return f"{before} -> {after}"


_RUNTIME_CONTEXT: dict[str, Any] = {}


def set_escalation_runtime_context(
    *,
    attempt_seq: int,
    research_seconds_left: float | None,
    hard_seconds_left: float | None,
) -> None:
    """Per-read scalars supplied by the runtime (never a mapping reference).

    The escalation happens inside the adapter, which cannot see the run's
    wave/claim/budget; the runtime stamps these per-read values before the read
    so the escalation outcome can carry them. Scalars only - the §71A-1 rule
    about long-lived references applies to mappings, not to numbers.
    """

    _RUNTIME_CONTEXT["attempt_seq"] = int(attempt_seq)
    _RUNTIME_CONTEXT["research_seconds_left"] = (
        float(research_seconds_left) if research_seconds_left is not None else None
    )
    _RUNTIME_CONTEXT["hard_seconds_left"] = (
        float(hard_seconds_left) if hard_seconds_left is not None else None
    )


__all__ = [
    "BROWSER_TIER_ENV",
    "set_escalation_runtime_context",
    "ESCALATION_BROWSER",
    "ESCALATION_ENV",
    "ESCALATION_HTTP",
    "ESCALATION_OFF",
    "EscalationOutcome",
    "TIER_BROWSER",
    "TIER_HTTP",
    "browser_tier_allowed",
    "escalate_read",
    "escalation_mode",
]
