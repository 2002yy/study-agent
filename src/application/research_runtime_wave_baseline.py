"""Resume-safe baseline ownership at the beginning of an active research wave.

Only the executor may checkpoint. This context prepares the wave identity and
its original state snapshot; restoration must read the *current* durable context
after that checkpoint, which may have rebound live values.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.contracts import EvidenceGap, ResearchState


ACTIVE_RESEARCH_WAVE_BASELINE_KEY = "claim_engine_wave_baseline"


@dataclass(frozen=True, slots=True)
class ActiveWaveBaselineContext:
    """Bind one active execution's live owner, never a cached state snapshot."""

    live: ActiveRuntimeLiveValues
    actionable_gaps: Callable[[ResearchState], tuple[EvidenceGap, ...]]

    def begin_if_needed(self, wave_id: str) -> bool:
        """Prepare cursor first, then baseline; caller checkpoints if True.

        On resume of the same wave the original baseline is authoritative and
        must not be overwritten by the state after partially completed reads.
        """
        if self.live.current_cursor().wave_id == wave_id:
            return False
        state = self.live.current_state()
        active_gap_ids = tuple(gap.id for gap in self.actionable_gaps(state))
        self.live.set_cursor(
            replace(self.live.current_cursor(), wave_id=wave_id, active_gap_ids=active_gap_ids)
        )
        self.live.current_context()[ACTIVE_RESEARCH_WAVE_BASELINE_KEY] = state.to_dict()
        return True

    def restore(self) -> ResearchState:
        """Resolve the latest rebound context, preserving evidence validation."""
        baseline_raw = self.live.current_context().get(ACTIVE_RESEARCH_WAVE_BASELINE_KEY)
        if not isinstance(baseline_raw, Mapping):
            raise ValueError("active wave baseline is unavailable")
        return ResearchState.from_dict(
            baseline_raw,
            known_evidence_ids=tuple(
                item["evidence_id"]
                for item in baseline_raw.get("evidence", [])
                if isinstance(item, Mapping)
                and isinstance(item.get("evidence_id"), str)
            ),
        )
