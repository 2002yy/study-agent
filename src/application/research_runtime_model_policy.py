"""Policy admission and bounded audit projection for active research calls.

The executor still owns provider calls, checkpoints and cost settlement. This
module only checks policy against the *current* context and records its audit.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues

ACTIVE_RESEARCH_POLICY_AUDITS_KEY = "claim_engine_policy_audits"


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


@dataclass(frozen=True, slots=True)
class RuntimeModelPolicyContext:
    """Check model policy against the execution's latest research context."""

    live: ActiveRuntimeLiveValues
    policy_check: Callable[[dict[str, Any], str], Any]
    utc_now: Callable[[], Any]

    def allowed(
        self,
        purpose: str,
        categories: tuple[str, ...],
    ) -> bool:
        """Check first, then audit on the same current context without persisting.

        A new call observes a rebound context; an in-flight policy check keeps
        its original audit target even if callbacks replace the live mapping.
        """

        context = self.live.current_context()
        allowed = bool(self.policy_check(context, purpose))
        context[ACTIVE_RESEARCH_POLICY_AUDITS_KEY] = updated_model_policy_audits(
            context.get(ACTIVE_RESEARCH_POLICY_AUDITS_KEY, []),
            purpose=purpose,
            categories=categories,
            allowed=allowed,
            checked_at=self.utc_now(),
        )
        return allowed
