"""Research-window telemetry separated from budget and checkpoint ownership.

The runtime supplies the *current* context and hard limit each time.  This
observer neither decides whether work can start nor persists a checkpoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


@dataclass(frozen=True, slots=True)
class ResearchWindowDiagnostics:
    """Owns the fixed finalization reserve, never the mutable run context."""

    reserve_seconds: float

    def record_end(
        self,
        context: dict[str, Any],
        *,
        hard_seconds: float,
        elapsed: Callable[[], float],
        exhausted: bool,
    ) -> None:
        """Write telemetry before the caller checkpoints it.

        There must be *two* calls to elapsed, matching the prior runtime
        closure: timing observations are not folded into one sampled value.
        """

        metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
        metrics["research_window"] = {
            "reserve_seconds": self.reserve_seconds,
            "hard_seconds": hard_seconds,
            "deadline_elapsed": round(hard_seconds - self.reserve_seconds, 3),
            "research_elapsed_seconds": round(elapsed(), 3),
            "remaining_after_research_seconds": round(
                hard_seconds - elapsed(), 3
            ),
            "exhausted": exhausted,
        }

    def record_skip(self, context: dict[str, Any], key: str) -> None:
        """Count window-refused work without creating a read outcome."""

        metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
        skips = metrics.get("research_window_skips")
        if not isinstance(skips, dict):
            skips = {}
            metrics["research_window_skips"] = skips
        skips[key] = int(skips.get(key) or 0) + 1
