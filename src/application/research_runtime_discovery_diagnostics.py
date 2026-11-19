"""Live lead-discovery and deeper-page targeting diagnostics.

These counters are audit-only. The runtime cursor remains the durable source of
discovery outcomes, while metrics may be rebound on checkpoint or recovery.
Resolve the current context for *each* observation, never retain its dict.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.deeper_targeting import (
    AUTHORITY_OFFICIAL,
    AUTHORITY_TUTORIAL,
    GapHint,
    authority_class,
    target_path_hit,
)
from src.web.research.page_intent import PageIntent, selection_reason
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


@dataclass(frozen=True)
class ActiveDiscoveryDiagnosticsContext:
    """Own discovery metric mutations without owning the live research state."""

    live: ActiveRuntimeLiveValues

    def bump_lead(self, key: str, amount: int = 1) -> None:
        """Keep legacy nonnegative counters, using the latest context."""

        metrics = self.live.current_context().setdefault(
            ACTIVE_RESEARCH_METRICS_KEY, {}
        )
        state = metrics.get("lead_discovery")
        if not isinstance(state, dict):
            state = {}
            metrics["lead_discovery"] = state
        state[key] = int(state.get(key) or 0) + max(0, int(amount))

    def record_targeting(
        self,
        *,
        gap: GapHint | None,
        source_url: str,
        selected_url: str,
        selected_depth: int,
        intent: PageIntent | None = None,
        variants: tuple[str, ...] = (),
    ) -> None:
        """Append bounded targeting observations, never cursor qualifications."""

        metrics = self.live.current_context().setdefault(
            ACTIVE_RESEARCH_METRICS_KEY, {}
        )
        state = metrics.get("deeper_targeting")
        if not isinstance(state, dict):
            state = {"gap_unavailable": 0, "strategy_counts": {}, "recent": []}
            metrics["deeper_targeting"] = state
        if gap is None:
            state["gap_unavailable"] = int(state.get("gap_unavailable") or 0) + 1
        else:
            counts = state.get("strategy_counts")
            if not isinstance(counts, dict):
                counts = {}
                state["strategy_counts"] = counts
            key = gap.targeting_strategy
            counts[key] = int(counts.get(key) or 0) + 1
            if intent is not None:
                intent_counts = state.get("page_intent_counts")
                if not isinstance(intent_counts, dict):
                    intent_counts = {}
                    state["page_intent_counts"] = intent_counts
                intent_counts[intent.kind] = (
                    int(intent_counts.get(intent.kind) or 0) + 1
                )
        recent = state.get("recent")
        if not isinstance(recent, list):
            recent = []
            state["recent"] = recent
        source_authority = gap.source_authority_class if gap else ""
        selected_authoritative = bool(
            gap is not None
            and selected_url
            and authority_class(selected_url) != AUTHORITY_TUTORIAL
            and (
                gap.source_authority_class == AUTHORITY_OFFICIAL
                or target_path_hit(selected_url)
            )
        )
        recent.append(
            {
                "followup_reason": (
                    "missing_target_fact"
                    if gap is not None
                    else "lead_without_usable_gap"
                ),
                "source_candidate_url": str(source_url or "")[:300],
                "source_authority_class": source_authority,
                "targeting_strategy": gap.targeting_strategy if gap else "unspecified",
                "gap_hint": gap.to_dict() if gap else {},
                "page_intent": intent.to_dict() if intent is not None else {},
                "query_variants": list(variants[:3]),
                "selected_query_variant": variants[0] if variants else "",
                "selection_reason": selection_reason(
                    authoritative=selected_authoritative,
                    title_match=0,
                    intent_match=len(intent.path_terms) if intent is not None else 0,
                ),
                "selected_candidate_url": str(selected_url or "")[:300],
                "selected_candidate_depth": int(selected_depth or 0),
            }
        )
        del recent[:-8]
