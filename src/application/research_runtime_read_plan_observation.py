"""Read-plan reserve observation, independent of candidate scheduling.

The scheduler owns reserve decisions. This writer receives their resolved
values and emits the unchanged diagnostic shape into the caller's current
metrics mapping. It never computes a new limit or retains the mapping.
"""

from __future__ import annotations

from typing import Any


def record_read_plan_reserve(
    metrics: dict[str, Any],
    *,
    configured: int,
    reclaimed: int,
    reclaim_reason: str,
    hard_cap: int,
    reads_used: int,
) -> None:
    """Preserve historical reserve fields, replacing only this observation."""

    metrics["read_reserve"] = {
        "configured": configured,
        "reclaimed": reclaimed,
        "reclaim_reason": reclaim_reason,
        "hard_cap": hard_cap,
        "reads_used": reads_used,
    }
