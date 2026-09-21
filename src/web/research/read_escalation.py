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
        }
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


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
) -> tuple[Mapping[str, Any] | None, EscalationOutcome]:
    """Try one escalation for an inadequate read.

    Returns ``(result, outcome)`` where ``result`` is the current reader's
    payload unless the escalation produced adequate content. Any failure leaves
    the original payload untouched and is recorded as a terminal retrieval
    failure.
    """

    outcome = EscalationOutcome(
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
            # fail closed: a misconfigured daemon must not be "tried anyway"
            outcome.reason = "misconfigured"
            _record_attempt(
                metrics_provider,
                outcome,
                claim_id=claim_id,
                wave_index=wave_index,
                backend_name=str(getattr(backend, "name", "wigolo")),
                state="skipped_no_budget" if status == "unavailable" else "blocked",
                result_count=0,
                bytes_=0,
            )
            return current, outcome

    outcome.attempted = True
    outcome.tier = TIER_HTTP
    fetched: RawReadArtifact | None = None
    try:
        fetched = backend.fetch(ReadRequest(url=url, max_chars=max_chars or 0))
    except Exception as exc:  # noqa: BLE001 - shadow/fallback must never raise
        outcome.state = "transport_error"
        outcome.reason = f"{type(exc).__name__}"
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
    failure_state = str((artifact.external_metadata or {}).get("state") or "")
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
        | {"tier": outcome.tier or TIER_HTTP, "transition": _transition(outcome)}
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


__all__ = [
    "BROWSER_TIER_ENV",
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
