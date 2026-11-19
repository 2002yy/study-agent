"""Shared retry observations for page reads and inventory/sitemap fetches.

The two I/O classes use the same retry admission policy but publish distinct
diagnostic keys. This module never owns the current research context, read
budget, or checkpoint: every call receives the caller's latest values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.web.research.read_retry import (
    make_window_admission,
    read_retry_mode,
    read_with_bounded_retry,
)
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _inventory_fetch_with_retry(
    url: str,
    *,
    context: dict[str, Any],
    remaining_seconds: Any,
    fetch: Any = None,
) -> tuple[str, str, str, str]:
    """Bounded, window-aware inventory fetch with separate diagnostics.

    The fetch adapter raises on transport failures and returns a 4-tuple;
    retry scheduling speaks in ``{"ok": ...}`` mappings. The admission rule
    and original attempt/order are controlled by the shared retry primitive.
    """

    if fetch is None:
        from src.news.article_fetcher import _fetch_text_payload

        fetch = _fetch_text_payload

    def _inner(target: str) -> Mapping[str, Any]:
        try:
            text, final_url, content_type, reason = fetch(
                target, timeout=12, max_bytes=1_500_000
            )
        except Exception as exc:  # transport exceptions are retryable
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not text:
            return {
                "ok": False,
                "reason": str(reason or "empty_response"),
                "content_type": content_type,
            }
        return {
            "ok": True,
            "text": text,
            "final_url": final_url,
            "content_type": content_type,
        }

    mode = read_retry_mode()
    if mode == "off":
        payload = dict(_inner(url))
    else:
        admission = None
        if mode == "window_aware":
            admission = make_window_admission(remaining_seconds=remaining_seconds)
        payload = read_with_bounded_retry(
            url,
            read_fn=_inner,
            admission=admission,
            diagnostics_key="inventory_fetch",
        )
        _accumulate_fetch_metrics(
            context, "inventory_fetch", payload.get("inventory_fetch")
        )
    if payload.get("ok") is True:
        return (
            str(payload.get("text") or ""),
            str(payload.get("final_url") or url),
            str(payload.get("content_type") or ""),
            "",
        )
    return (
        "",
        "",
        "",
        str(payload.get("error") or payload.get("reason") or "fetch_failed"),
    )


def _accumulate_fetch_metrics(
    context: dict[str, Any], key: str, diagnostics: Any
) -> None:
    """Aggregate bounded retry audit data into the supplied live context.

    The read and inventory metrics remain separate even though both use the
    same retry rules. Observation does not admit, retry, or charge any read.
    """

    if not isinstance(diagnostics, Mapping):
        return
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    entry = metrics.get(key)
    if not isinstance(entry, dict):
        entry = {
            "fetches": 0,
            "attempts": 0,
            "retries": 0,
            "skipped_due_to_budget": 0,
            "retry_reasons": [],
            "admission_reasons": [],
        }
        metrics[key] = entry
    entry["fetches"] = int(entry.get("fetches") or 0) + 1
    entry["attempts"] = int(entry.get("attempts") or 0) + int(
        diagnostics.get("attempts") or 0
    )
    entry["retries"] = int(entry.get("retries") or 0) + int(
        diagnostics.get("retries") or 0
    )
    entry["skipped_due_to_budget"] = int(entry.get("skipped_due_to_budget") or 0) + int(
        diagnostics.get("skipped_due_to_budget") or 0
    )
    entry["retry_backoff_ms"] = round(
        float(entry.get("retry_backoff_ms") or 0.0)
        + float(diagnostics.get("retry_backoff_ms") or 0.0),
        1,
    )
    entry["retry_fetch_ms"] = round(
        float(entry.get("retry_fetch_ms") or 0.0)
        + float(diagnostics.get("retry_fetch_ms") or 0.0),
        1,
    )
    reasons = entry.get("retry_reasons")
    if not isinstance(reasons, list):
        reasons = []
    reasons.extend(
        str(item)[:160] for item in (diagnostics.get("retry_reasons") or [])[:4]
    )
    entry["retry_reasons"] = reasons[-8:]
    admission_reasons = entry.get("admission_reasons")
    if not isinstance(admission_reasons, list):
        admission_reasons = []
    admission_reasons.extend(
        str(item)[:80] for item in (diagnostics.get("admission_reasons") or [])[:4]
    )
    entry["admission_reasons"] = admission_reasons[-8:]
