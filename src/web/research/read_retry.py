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
import time
from typing import Any, Callable, Mapping

READ_RETRY_ENV = "RESEARCH_READ_RETRY"
MAX_READ_RETRIES = 2
READ_RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0)

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
) -> dict[str, Any]:
    """Run one read with bounded fetch-layer retries and additive diagnostics."""

    attempts = 0
    retry_reasons: list[str] = []
    retried = 0
    result: Mapping[str, Any] = {}
    while True:
        attempts += 1
        try:
            result = read_fn(url) or {}
        except Exception as exc:  # transport exceptions count as fetch failures
            result = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        if result.get("ok") is True:
            break
        if retried >= max(0, int(max_retries)):
            break
        if not is_fetch_layer_failure(result):
            break
        retry_reasons.append(
            str(result.get("error") or result.get("reason") or "")[:160]
        )
        retried += 1
        if backoff_seconds:
            sleep(backoff_seconds[min(retried - 1, len(backoff_seconds) - 1)])
    payload = dict(result)
    if retried:
        payload["read_retry"] = {
            "attempts": attempts,
            "retries": retried,
            "retry_reasons": retry_reasons,
        }
    return payload


__all__ = [
    "FETCH_FAILURE_MARKERS",
    "MAX_READ_RETRIES",
    "READ_RETRY_BACKOFF_SECONDS",
    "READ_RETRY_ENV",
    "is_fetch_layer_failure",
    "read_retry_enabled",
    "read_with_bounded_retry",
]
