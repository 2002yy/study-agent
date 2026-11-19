"""Mutable per-wave read charges, separate from the live research budget.

Evidence reads and lead-discovery reads spend the same slots and character
allowance.  This context owns only the charges accumulated during one wave;
the executor supplies the *current* budget limits at each admission and keeps
ownership of ResearchState, checkpoints and budget settlement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.web.research.deep_runtime import seed_char_charge
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


@dataclass(slots=True)
class ReadWaveQuotaContext:
    successful_reads: int
    used_chars: int

    @classmethod
    def restore(
        cls,
        *,
        budget_reads_used: int,
        context: dict[str, Any],
        selected_sources: list[dict[str, Any]],
    ) -> ReadWaveQuotaContext:
        """Restore existing charges without retaining replaceable run inputs."""

        used_chars = sum(
            int(item.get("content_chars") or 0)
            for item in context.get(ACTIVE_RESEARCH_METRICS_KEY, {}).get("reads", [])
            if isinstance(item, Mapping)
        ) + seed_char_charge(selected_sources)
        return cls(successful_reads=budget_reads_used, used_chars=used_chars)

    def exhausted(self, *, max_reads: int, max_total_chars: int) -> bool:
        """Use the latest state limits, including any steering/recovery changes."""

        return (
            self.successful_reads >= max_reads
            or self.used_chars >= max_total_chars
        )

    def remaining_chars(self, *, max_total_chars: int) -> int:
        """Deep local materialization uses the full remaining character budget."""

        return max_total_chars - self.used_chars

    def source_limit(self, *, max_total_chars: int, cap: int = 6000) -> int:
        """Return the original bounded quota; admission remains the caller's job."""

        return min(cap, self.remaining_chars(max_total_chars=max_total_chars))

    def charge_materialization(self, content: str) -> None:
        """Local Deep seed materialization spends characters, never a read slot."""

        self.used_chars += len(content)

    def charge_read(self, content: str) -> None:
        """A successful evidence or discovery read spends a slot and characters."""

        self.successful_reads += 1
        self.used_chars += len(content)
