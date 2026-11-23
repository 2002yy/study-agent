"""Live discovery funnel, lead and deeper-page targeting diagnostics.

These counters are audit-only. The runtime cursor remains the durable source of
discovery outcomes, while metrics may be rebound on checkpoint or recovery.
Resolve the current context for *each* observation, never retain its dict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_assessment_results import assessment_store
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.web.research.deeper_targeting import (
    AUTHORITY_OFFICIAL,
    AUTHORITY_TUTORIAL,
    GapHint,
    authority_class,
    target_path_hit,
)
from src.web.research.domain_targeted import DISCOVERY_METHOD_DOMAIN_TARGETED
from src.web.research.llm_proposal import DISCOVERY_METHOD_LLM_PROPOSED
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

    def record_lead_candidate_ids(self) -> None:
        """Project lead-discovered IDs from the current durable cursor.

        Only call this after new candidates have been appended, as before.
        Neither cached cursor references nor a separate candidate list are kept.
        """

        metrics = self.live.current_context().setdefault(
            ACTIVE_RESEARCH_METRICS_KEY, {}
        )
        metrics["lead_discovered_candidate_ids"] = [
            item.id
            for item in self.live.current_cursor().candidates
            if item.discovery_method == "lead_url"
        ]

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


    def record_tier2_funnel(
        self,
        *,
        brief: Mapping[str, Any],
        selected_sources: list[dict[str, Any]],
    ) -> None:
        """Join proposals, assessments, reads, extraction and Gate eligibility."""

        context = self.live.current_context()
        cursor = self.live.current_cursor()
        metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
        if not isinstance(metrics, dict):
            return
        proposals: list[tuple[str, Mapping[str, Any]]] = []
        for key, method in (
            ("tier2_proposal", DISCOVERY_METHOD_LLM_PROPOSED),
            ("domain_targeted", DISCOVERY_METHOD_DOMAIN_TARGETED),
        ):
            records = metrics.get(key)
            if isinstance(records, list):
                proposals.extend((method, record) for record in records if isinstance(record, Mapping))
        if not proposals:
            return
        assessments = assessment_store(context)
        relevant_ids: set[str] = set()
        for ranked in assessments.values():
            if not isinstance(ranked, list):
                continue
            for row in ranked:
                if not isinstance(row, Mapping):
                    continue
                assessment = row.get("assessment")
                candidate = row.get("candidate")
                if not isinstance(assessment, Mapping) or not isinstance(candidate, Mapping):
                    continue
                if str(assessment.get("relevance") or "") == "answer_relevant":
                    relevant_ids.add(str(candidate.get("id") or ""))
        completed_reads = set(cursor.completed_read_ids)
        extraction_by_candidate: dict[str, list[str]] = {}
        for source in selected_sources:
            if not isinstance(source, Mapping):
                continue
            candidate_id = str(source.get("candidate_id") or "")
            extractions = source.get("extractions")
            relations: list[str] = []
            if isinstance(extractions, Mapping):
                for summary in extractions.values():
                    if isinstance(summary, Mapping):
                        relation = str(summary.get("relation") or "")
                        if relation:
                            relations.append(relation)
            extraction_by_candidate[candidate_id] = sorted(set(relations))
        eligible_ids = {
            str(row.get("evidence_id") or "")
            for row in brief.get("eligible_evidence") or []
            if isinstance(row, Mapping)
        }
        evidence_by_candidate = {
            outcome.candidate_id: outcome.evidence_id
            for outcome in cursor.read_outcomes
            if outcome.evidence_id
        }
        rows: list[dict[str, Any]] = []
        for method, record in proposals:
            for candidate_id in record.get("added_candidate_ids") or []:
                evidence_id = evidence_by_candidate.get(str(candidate_id), "")
                rows.append(
                    {
                        "claim_id": record.get("claim_id"),
                        "candidate_id": candidate_id,
                        "discovery_method": method,
                        "proposed": True,
                        "assessed_answer_relevant": str(candidate_id) in relevant_ids,
                        "read": str(candidate_id) in completed_reads,
                        "extraction_relations": extraction_by_candidate.get(
                            str(candidate_id), []
                        ),
                        "gate_eligible": bool(evidence_id) and evidence_id in eligible_ids,
                    }
                )
        metrics["discovery_funnel"] = {
            "proposed_candidates": len(rows),
            "by_discovery_method": {
                method: sum(1 for row in rows if row["discovery_method"] == method)
                for method in sorted({row["discovery_method"] for row in rows})
            },
            "assessed_answer_relevant": sum(
                1 for row in rows if row["assessed_answer_relevant"]
            ),
            "read": sum(1 for row in rows if row["read"]),
            "extracted_supports": sum(
                1 for row in rows if "supports" in row["extraction_relations"]
            ),
            "gate_eligible": sum(1 for row in rows if row["gate_eligible"]),
            "rows": rows,
        }
