"""Budget and audit bridge for visual reads.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.13 boundaries 3 and 4.

A vision call is a **model call**, not a read: it must never be charged to
``reads_used``. It must still consume the *same* research clock, so the number of
allowed vision calls is derived from the runtime budget plus an explicit operator
setting, and it collapses to zero as soon as the hard deadline is close.

The default is **0**: wiring the pipeline into production does not by itself make
the engine look at images (production-capable, default-inert -- the same posture
used for the P1 reader hints and the Crawl4AI specialist).
"""

from __future__ import annotations

import os
from typing import Any, MutableMapping

from src.web.research.contracts import ResearchState
from src.web.research.multimodal_reader import VisualReadBudget

MAX_VISION_CALLS_ENV = "RESEARCH_VISION_MAX_CALLS"

#: Below this much remaining hard time, no vision call may be attempted.
MIN_REMAINING_SECONDS_FOR_VISION = 5.0

AUDIT_PURPOSE = "image_description"
AUDIT_DATA_CATEGORIES: tuple[str, ...] = ("image_content",)
VISUAL_AUDIT_KEY = "visual_external_calls"


def configured_max_vision_calls() -> int:
    """Operator setting; absent / malformed / negative means "no vision"."""

    raw = (os.getenv(MAX_VISION_CALLS_ENV) or "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(0, value)


def visual_read_budget(state: ResearchState | None) -> VisualReadBudget:
    """Derive the vision-call allowance from the runtime budget (same clock)."""

    allowed = configured_max_vision_calls()
    if state is None or allowed == 0:
        return VisualReadBudget(max_vision_calls=0)
    budget = state.budget
    remaining = budget.hard_timeout_seconds - budget.elapsed_seconds
    if remaining < MIN_REMAINING_SECONDS_FOR_VISION:
        return VisualReadBudget(max_vision_calls=0)
    return VisualReadBudget(max_vision_calls=allowed)


def visual_audit_record(
    *,
    image_id: str,
    evidence_id: str,
    status: str,
    model: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """The research-side analogue of the G14-c attachment external-call record."""

    return {
        "purpose": AUDIT_PURPOSE,
        "provider": "deepseek",
        "model": str(model or ""),
        "data_categories": list(AUDIT_DATA_CATEGORIES),
        "status": str(status or ""),
        "image_id": str(image_id or ""),
        "evidence_id": str(evidence_id or ""),
        "reason": str(reason or ""),
    }


def record_visual_audit(
    context: MutableMapping[str, Any],
    record: dict[str, Any],
) -> None:
    """Append one audit record to the run context (bounded, never raises)."""

    try:
        entries = context.get(VISUAL_AUDIT_KEY)
        if not isinstance(entries, list):
            entries = []
            context[VISUAL_AUDIT_KEY] = entries
        entries.append(dict(record))
    except Exception:  # noqa: BLE001 - audit must never break a read
        return


__all__ = [
    "AUDIT_DATA_CATEGORIES",
    "AUDIT_PURPOSE",
    "MAX_VISION_CALLS_ENV",
    "MIN_REMAINING_SECONDS_FOR_VISION",
    "VISUAL_AUDIT_KEY",
    "configured_max_vision_calls",
    "record_visual_audit",
    "visual_audit_record",
    "visual_read_budget",
]
