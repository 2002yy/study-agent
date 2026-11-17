"""Pure bounded policy-audit projection for active research model calls.

Policy authorization itself remains with the executor; this module does not
call a provider, persist a checkpoint or settle a model attempt.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def updated_model_policy_audits(
    previous: Iterable[object],
    *,
    purpose: str,
    categories: tuple[str, ...],
    allowed: bool,
    checked_at: Any,
) -> list[dict[str, Any]]:
    """Preserve audit shape, order and 100-entry cap without mutating input."""

    audits = [dict(item) for item in previous if isinstance(item, Mapping)]
    audits.append(
        {
            "call_id": f"policy:{purpose}:{len(audits) + 1}",
            "purpose": purpose,
            "status": "allowed" if allowed else "blocked_by_policy",
            "data_categories": list(categories),
            "checked_at": checked_at,
        }
    )
    return audits[-100:]
