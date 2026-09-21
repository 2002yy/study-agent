"""§48 bounded reader retry for fetch-layer transient failures.

Diagnostic, default off (``RESEARCH_READ_RETRY=on``). Frozen policy from §47:
at most two retries, deterministic 1s/2s backoff, and **only** fetch-layer
failures are retried. A successful fetch that yields short text (the §46
``short_doc`` content shape) is never retried - that is a content problem, not
a network problem. Policy, URL and extraction semantics are untouched.

The retried read returns the final reader payload plus additive diagnostics
(``read_retry``) so the runtime can keep the attempt distribution auditable.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

READ_RETRY_ENV = "RESEARCH_READ_RETRY"
READ_RETRY_FLOOR_ENV = "RESEARCH_READ_RETRY_FLOOR_SECONDS"
MAX_READ_RETRIES = 2
READ_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0)
# §50/B2: the window-aware admission rule is a *formula*, not a magic floor:
#
#     retry_allowed = remaining_research_time
#                     >= attempt_budget + next_backoff + finalization_reserve
#
# 18s (the §49 provisional floor) is simply this formula's first instance:
# 12s attempt ceiling + 1s backoff + 5s reserve. The components stay parameters
# so the next characterization round calibrates the rule rather than the number.
READ_RETRY_ATTEMPT_BUDGET_SECONDS = 12.0
READ_RETRY_RESERVE_SECONDS = 5.0
# Kept only as an experimental override (must not exceed the computed
# requirement); it exists so §48/§49 runs remain reproducible.
READ_RETRY_WINDOW_FLOOR_SECONDS = 18.0

# Fetch-layer signatures only. Deliberately excludes shape/policy failures
# such as "unsafe_or_empty_url", "non_html_resource" and any successful read.
FETCH_FAILURE_MARKERS = (
    "urlerror",
    "remotedisconnected",
    "10054",
    "connection reset",
    "connectionreset",
    "reset by peer",
    "connection aborted",
    "connection refused",
    "timed out",
    "timeout",
    "server disconnected",
    "temporarily unavailable",
    "network is unreachable",
    "name or service not known",
    "getaddrinfo",
)


def read_retry_enabled() -> bool:
    raw = (os.getenv(READ_RETRY_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def read_retry_mode() -> str:
    """``off`` (default) | ``unbounded`` | ``window_aware``.

    ``on``/``1``/``yes`` keep the §48 unbounded behaviour for
    reproducibility; ``window_aware`` additionally requires the admission
    floor (remaining research time) before every retry.
    """

    raw = (os.getenv(READ_RETRY_ENV) or "").strip().lower()
    if raw in {"window_aware", "window-aware", "aware"}:
        return "window_aware"
    if raw in {"1", "true", "on", "yes", "unbounded"}:
        return "unbounded"
    return "off"


def retry_window_floor_seconds() -> float:
    raw = os.getenv(READ_RETRY_FLOOR_ENV)
    try:
        value = float(raw) if raw not in (None, "") else READ_RETRY_WINDOW_FLOOR_SECONDS
    except (TypeError, ValueError):
        value = READ_RETRY_WINDOW_FLOOR_SECONDS
    return max(1.0, min(value, 120.0))


def retry_window_requirement(
    retry_number: int,
    *,
    attempt_budget_seconds: float | None = None,
    backoff_seconds: tuple[float, ...] | None = None,
    reserve_seconds: float | None = None,
) -> float:
    """Seconds a retry needs before it is admitted (the §50/B2 formula)."""

    attempt = (
        READ_RETRY_ATTEMPT_BUDGET_SECONDS
        if attempt_budget_seconds is None
        else float(attempt_budget_seconds)
    )
    reserve = (
        READ_RETRY_RESERVE_SECONDS
        if reserve_seconds is None
        else float(reserve_seconds)
    )
    schedule = READ_RETRY_BACKOFF_SECONDS if backoff_seconds is None else tuple(backoff_seconds)
    index = max(0, min(int(retry_number) - 1, len(schedule) - 1)) if schedule else 0
    backoff = float(schedule[index]) if schedule else 0.0
    return attempt + backoff + reserve


@dataclass(frozen=True)
class RetryAdmission:
    """Outcome of one admission check, with the numbers that produced it."""

    allowed: bool
    reason: str
    remaining_seconds: float
    required_seconds: float

    def __bool__(self) -> bool:  # so plain ``if admission(...)`` keeps working
        return self.allowed


def make_window_admission(
    *,
    remaining_seconds: Callable[[], float],
    floor_seconds: float | None = None,
    attempt_budget_seconds: float | None = None,
    backoff_seconds: tuple[float, ...] | None = None,
    reserve_seconds: float | None = None,
) -> Callable[[int], RetryAdmission]:
    """Admission callable re-evaluated before *every* retry.

    The requirement is recomputed per retry from the observed remaining time,
    so an initially-admitted retry never grants the following one: retry #2 is
    re-checked (and needs a larger window, because its backoff is longer).
    """

    def admission(retry_number: int) -> RetryAdmission:
        required = retry_window_requirement(
            retry_number,
            attempt_budget_seconds=attempt_budget_seconds,
            backoff_seconds=backoff_seconds,
            reserve_seconds=reserve_seconds,
        )
        if floor_seconds is not None:
            required = max(required, float(floor_seconds))
        remaining = float(remaining_seconds())
        allowed = remaining >= required
        return RetryAdmission(
            allowed=allowed,
            reason="allowed" if allowed else "insufficient_window",
            remaining_seconds=remaining,
            required_seconds=required,
        )

    return admission


REASON_REPEATED_SIGNATURE = "repeated_error_signature"
REASON_INSUFFICIENT_WINDOW = "insufficient_remaining_window"


def error_signature(result: Mapping[str, Any] | None) -> str:
    """Coarse, host/url-independent signature of a failure.

    Deliberately does not name any specific error code: it keeps the exception
    class plus the numeric errno/winerror if one is present, and otherwise falls
    back to a trimmed message. Two failures with the same signature are "the
    same kind of failure happening again", which is all A' needs.
    """

    if not isinstance(result, Mapping):
        return ""
    text = " ".join(
        str(result.get(key) or "")
        for key in ("error", "reason", "status", "error_code")
    ).strip()
    if not text:
        return ""
    lowered = text.lower()
    for marker in FETCH_FAILURE_MARKERS:
        if marker in lowered:
            kind = marker
            break
    else:
        kind = lowered.split(":")[0][:40]
    codes = re.findall(r"(?:winerror|errno|error)\s*[: ]?\s*(\d+)", lowered)
    digits = re.findall(r"\b(\d{3,5})\b", lowered)
    code = codes[0] if codes else (digits[0] if digits else "")
    return f"{kind}#{code}" if code else kind


def is_fetch_layer_failure(result: Mapping[str, Any] | None) -> bool:
    """True only when the read failed at the fetch/transport layer."""

    if not isinstance(result, Mapping):
        return False
    if result.get("ok") is True:
        return False
    text = " ".join(
        str(result.get(key) or "")
        for key in ("error", "reason", "status", "error_code")
    ).lower()
    if not text.strip():
        return False
    return any(marker in text for marker in FETCH_FAILURE_MARKERS)


def read_with_bounded_retry(
    url: str,
    *,
    read_fn: Callable[[str], Mapping[str, Any]],
    max_retries: int = MAX_READ_RETRIES,
    backoff_seconds: tuple[float, ...] = READ_RETRY_BACKOFF_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    admission: Callable[[int], Any] | None = None,
    diagnostics_key: str = "read_retry",
    clock: Callable[[], float] = time.monotonic,
    remaining_seconds: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Run one fetch with bounded fetch-layer retries and additive diagnostics.

    ``admission(retry_number)`` gates **each** retry (``True`` proceeds; a
    :class:`RetryAdmission` is accepted and its reason recorded). It is called
    again before every retry, so permission for retry #1 never implies
    permission for retry #2. A refused admission is recorded as
    ``skipped_by_admission`` / ``skipped_due_to_budget``.

    ``diagnostics_key`` names the additive payload field, keeping I/O classes
    separable: page reads report under ``read_retry`` and inventory fetches
    (sitemaps) under ``inventory_fetch``. The retry policy is shared; the
    metrics are not.
    """

    attempts = 0
    retry_reasons: list[str] = []
    admission_reasons: list[str] = []
    skipped_by_admission = 0
    retried = 0
    fetch_ms = 0.0
    backoff_ms = 0.0
    suppressed_backoff_ms = 0.0
    backoff_suppressed_reason = ""
    retry_suppressed_reason = ""
    last_signature = ""
    repeated_signature = False
    result: Mapping[str, Any] = {}
    # F2-O3a: per-attempt provenance. Only emitted for reads that actually
    # retried (or were refused a retry), so a clean single-attempt read keeps
    # its exact previous payload shape.
    attempts_detail: list[dict[str, Any]] = []
    while True:
        attempts += 1
        _attempt_started = clock()
        try:
            result = read_fn(url) or {}
        except Exception as exc:  # transport exceptions count as fetch failures
            result = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            attempt_ms = max(0.0, clock() - _attempt_started)
            fetch_ms += attempt_ms
        attempts_detail.append(
            {
                "index": attempts,
                "fetch_ms": round(attempt_ms * 1000.0, 1),
                "ok": result.get("ok") is True,
                # only a failure has a signature; a successful attempt must not
                # look like "the same failure again" to A'
                "signature": error_signature(result)
                if result.get("ok") is not True
                else "",
                "chars": len(
                    str(result.get("text") or result.get("content") or "")
                ),
                "content_type": str(result.get("content_type") or "")[:60],
            }
        )
        if result.get("ok") is True:
            break
        if retried >= max(0, int(max_retries)):
            break
        if not is_fetch_layer_failure(result):
            break
        # F2-O1b A': a failure whose signature equals the previous attempt's is
        # "the same failure happening again" - the next attempt may proceed, but
        # the wait before it buys nothing and is suppressed.
        signature = error_signature(result)
        repeated_signature = bool(signature) and signature == last_signature
        last_signature = signature or last_signature
        if admission is not None:
            decision = admission(retried + 1)
            if not bool(decision):
                skipped_by_admission += 1
                admission_reasons.append(
                    str(getattr(decision, "reason", "") or "insufficient_window")
                )
                break
            reason = str(getattr(decision, "reason", "") or "")
            if reason:
                admission_reasons.append(reason)
        retry_reasons.append(
            str(result.get("error") or result.get("reason") or "")[:160]
        )
        planned_backoff = 0.0
        if backoff_seconds:
            planned_backoff = backoff_seconds[min(retried, len(backoff_seconds) - 1)]
        if repeated_signature and planned_backoff:
            backoff_suppressed_reason = REASON_REPEATED_SIGNATURE
            suppressed_backoff_ms += planned_backoff
            planned_backoff = 0.0
        # F2-O1b B (deadline-preserving retry suppression): the retry may only
        # be issued when the wait *plus* a conservative estimate of the next
        # fetch still fits the remaining window. The estimate reuses the last
        # attempt's own elapsed time - no new latency model.
        if remaining_seconds is not None:
            # fetch_ms accumulates clock *seconds* here (converted to ms only
            # in the diagnostics), so the estimate is used as-is.
            expected_fetch = fetch_ms if attempts else 0.0
            try:
                remaining = float(remaining_seconds())
            except Exception:
                remaining = 0.0
            if planned_backoff + expected_fetch > remaining:
                retry_suppressed_reason = REASON_INSUFFICIENT_WINDOW
                skipped_by_admission += 1
                admission_reasons.append(REASON_INSUFFICIENT_WINDOW)
                break
        retried += 1
        if planned_backoff:
            _backoff_started = clock()
            sleep(planned_backoff)
            backoff_ms += max(0.0, clock() - _backoff_started)
    payload = dict(result)
    if retried or skipped_by_admission:
        payload[diagnostics_key] = {
            "attempts": attempts,
            "retries": retried,
            "skipped_by_admission": skipped_by_admission,
            "skipped_due_to_budget": skipped_by_admission,
            "retry_reasons": retry_reasons,
            "admission_reasons": admission_reasons,
            # F2-S1: backoff waiting and real re-fetch time are separate costs
            # (the clock is monotonic seconds; the ledger speaks milliseconds)
            "retry_fetch_ms": round(fetch_ms * 1000.0, 1),
            "retry_backoff_ms": round(backoff_ms * 1000.0, 1),
            # F2-O1b: why idle waiting or a retry was removed - two distinct
            # reasons, never a single opaque "skipped"
            "suppressed_backoff_ms": round(suppressed_backoff_ms * 1000.0, 1),
            "backoff_suppressed_reason": backoff_suppressed_reason,
            "retry_suppressed_reason": retry_suppressed_reason,
            # F2-O3a: one row per attempt (index, fetch_ms, ok, signature,
            # chars, content_type) so a slow read can be attributed to a single
            # attempt rather than to the retry aggregate.
            "attempts_detail": attempts_detail[:4],
        }
    return payload


__all__ = [
    "FETCH_FAILURE_MARKERS",
    "REASON_INSUFFICIENT_WINDOW",
    "REASON_REPEATED_SIGNATURE",
    "error_signature",
    "MAX_READ_RETRIES",
    "READ_RETRY_ATTEMPT_BUDGET_SECONDS",
    "READ_RETRY_BACKOFF_SECONDS",
    "READ_RETRY_ENV",
    "READ_RETRY_FLOOR_ENV",
    "READ_RETRY_RESERVE_SECONDS",
    "READ_RETRY_WINDOW_FLOOR_SECONDS",
    "RetryAdmission",
    "is_fetch_layer_failure",
    "make_window_admission",
    "read_retry_enabled",
    "read_retry_mode",
    "read_with_bounded_retry",
    "retry_window_floor_seconds",
    "retry_window_requirement",
]
