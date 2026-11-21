"""Completed read-site specialist provenance, independent of routing.

This observer only appends the prior bounded diagnostic payload into the
context supplied *now* by the caller. It never schedules, invokes a reader,
updates a read attempt or settles a budget.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def record_read_site_specialist(
    context: dict[str, Any],
    *,
    route: Mapping[str, Any],
    specialist: Mapping[str, Any] | None,
    hint_source: str,
) -> None:
    """Durable selector provenance (independent of default attempt numbering)."""

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    specialist = specialist or {}
    attempted = bool(specialist)
    usable = bool(
        specialist.get("specialist_available")
        and getattr(specialist.get("result"), "usable_content", False)
    )
    entries = metrics.get("read_site_specialist")
    if not isinstance(entries, list):
        entries = []
    entries.append(
        {
            "requested_reader_capabilities": list(
                route.get("requested_reader_capabilities") or []
            ),
            "hint_source": str(hint_source or ""),
            "hint_honored": attempted and bool(specialist.get("specialist_available")),
            "specialist_attempted": attempted,
            "specialist_backend": str(specialist.get("actual_backend") or ""),
            "specialist_outcome": str(specialist.get("terminal_outcome") or ""),
            "specialist_usable": usable,
            "specialist_unavailable_reason": str(
                specialist.get("unavailable_reason") or route.get("reason") or ""
            ),
            "specialist_latency_ms": float(specialist.get("latency_ms") or 0.0),
            "fallback_used": not usable,
        }
    )
    metrics["read_site_specialist"] = entries[-60:]

