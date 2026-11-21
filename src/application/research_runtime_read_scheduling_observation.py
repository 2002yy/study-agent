"""Bounded read-admission diagnostics, separate from scheduling policy.

Read scheduling remains a pure decision over current candidate history and
backend health. This observer records the completed decision into the context
supplied by the caller, which may have changed after checkpoint/recovery.
No budget, cursor, attempt or backend state is changed here.
"""

from __future__ import annotations

from typing import Any

from src.web.research.progressive_routing import SchedulingDecision
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def record_read_scheduling_decision(
    context: dict[str, Any], decision: SchedulingDecision
) -> None:
    """Append the existing last-60 scheduling trace, including legacy resets."""

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    entries = metrics.get("read_scheduling")
    if not isinstance(entries, list):
        entries = []
    entries.append(decision.to_dict())
    metrics["read_scheduling"] = entries[-60:]
