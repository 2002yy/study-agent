"""One read plan's explicit mutable scheduling state.

This context only computes candidate reads and claim/extraction bindings. It
does not execute reads, update the durable cursor, checkpoint, or spend budgets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from math import ceil
from typing import Any

from src.web.research.candidate_ranking import RankedCandidate
from src.web.research.contracts import ResearchClaim, ResearchState
from src.web.research.scheduler import (
    ReadSchedulerPolicy,
    is_schedulable_candidate,
    plan_read_wave,
)
from src.web.research.selection_trace import SelectionTraceCollector


@dataclass(slots=True)
class FairReadPlanContext:
    """Own all per-plan mutable bindings, cluster coverage and read slots.

    A fresh instance is used per wave. Input rankings and durable coverage are
    read-only; trace and diagnostics receive the same observations as before.
    """

    state: ResearchState
    rankings: Mapping[str, tuple[RankedCandidate, ...]]
    covered_cluster_ids_by_claim: Mapping[str, set[str]] | None = None
    trace: SelectionTraceCollector | None = None
    diagnostics: dict[str, Any] | None = None
    physical: list[dict[str, str]] = field(default_factory=list, init=False)
    targets: list[dict[str, str]] = field(default_factory=list, init=False)
    physical_ids: set[str] = field(default_factory=set, init=False)
    target_pairs: set[tuple[str, str]] = field(default_factory=set, init=False)
    claim_clusters: dict[str, set[str]] = field(init=False)
    claims: dict[str, ResearchClaim] = field(init=False)
    open_conflict_claim_ids: set[str] = field(init=False)
    reserve: int = field(init=False)
    normal_limit: int = field(init=False)

    def __post_init__(self) -> None:
        self.claims = {claim.id: claim for claim in self.state.claims}
        # Copy prior-wave durable truth; adding a binding cannot modify the input.
        self.claim_clusters = {
            claim_id: set(cluster_ids)
            for claim_id, cluster_ids in (self.covered_cluster_ids_by_claim or {}).items()
        }
        self.open_conflict_claim_ids = {
            conflict.claim_id
            for conflict in self.state.conflict_gaps
            if conflict.state in {"open", "searching"}
        }
        self.reserve = ceil(self.state.budget.max_reads / 3)
        if self.open_conflict_claim_ids:
            reclaimed = 0
            reclaim_reason = "open_conflicts_present"
        else:
            reclaimed = self.reserve
            reclaim_reason = "no_open_conflicts"
        self.normal_limit = max(
            0,
            self.state.budget.max_reads
            - self.state.budget.reads_used
            - self.reserve
            + reclaimed,
        )
        if self.diagnostics is not None:
            self.diagnostics["read_reserve"] = {
                "configured": self.reserve,
                "reclaimed": reclaimed,
                "reclaim_reason": reclaim_reason,
                "hard_cap": self.state.budget.max_reads,
                "reads_used": self.state.budget.reads_used,
            }

    def bind(self, candidate_id: str, claim_id: str, item: RankedCandidate) -> None:
        pair = (candidate_id, claim_id)
        if pair in self.target_pairs:
            return
        self.target_pairs.add(pair)
        self.claim_clusters.setdefault(claim_id, set()).add(item.assessment.cluster_id)
        self.targets.append(
            {
                "candidate_id": candidate_id,
                "claim_id": claim_id,
                "cluster_id": item.assessment.cluster_id,
                "source_role": item.assessment.source_role,
            }
        )

    def schedule(
        self, claim_ids: list[str], wave_size: int, *, allow_reserve: bool = False
    ) -> None:
        for claim_id in claim_ids:
            ranked = tuple(
                item
                for item in self.rankings.get(claim_id, ())
                if (item.candidate.id, claim_id) not in self.target_pairs
            )
            if not ranked:
                continue
            # Reuse still needs the same per-claim eligibility as a fresh read.
            reusable = tuple(
                item
                for item in ranked
                if item.candidate.id in self.physical_ids
                and is_schedulable_candidate(item)
            )
            # Historical clusters are excluded before the per-claim wave cap.
            covered_clusters = self.claim_clusters.get(claim_id, set())
            fresh = tuple(
                item
                for item in ranked
                if item.candidate.id not in self.physical_ids
                and item.assessment.cluster_id not in covered_clusters
            )
            remaining = (
                self.state.budget.max_reads
                - self.state.budget.reads_used
                - len(self.physical)
            )
            budget_open = remaining > 0 and (
                allow_reserve or len(self.physical) < self.normal_limit
            )
            if self.trace is not None:
                fresh_ids = {item.candidate.id for item in fresh}
                for item in ranked:
                    if (
                        item.candidate.id in self.physical_ids
                        or item.candidate.id in fresh_ids
                    ):
                        continue
                    self.trace.note_scheduler(
                        item.candidate.canonical_url,
                        decision="rejected",
                        reason="covered_cluster",
                    )
                    self.trace.note_scheduler_rejected(
                        item.candidate.canonical_url, stage="covered_cluster"
                    )
                if not budget_open:
                    for item in fresh:
                        self.trace.note_scheduler_rejected(
                            item.candidate.canonical_url, stage="budget"
                        )

            conflict_open = claim_id in self.open_conflict_claim_ids or any(
                "new_contradiction" in item.assessment.expected_gain_signals
                for item in ranked
            )
            policy = ReadSchedulerPolicy(
                critical_wave_size=wave_size,
                major_wave_size=wave_size,
                context_wave_size=0,
            )
            fresh_selected: list[str] = []
            by_id: dict[str, RankedCandidate] = {}
            if budget_open and fresh:
                budget = replace(
                    self.state.budget,
                    reads_used=self.state.budget.reads_used + len(self.physical),
                )
                plan = plan_read_wave(
                    fresh,
                    claim=self.claims[claim_id],
                    budget=budget,
                    policy=policy,
                    conflict_open=conflict_open,
                    preserve_conflict_reserve=(
                        not allow_reserve and bool(self.open_conflict_claim_ids)
                    ),
                )
                by_id = {item.candidate.id: item for item in fresh}
                fresh_selected = [
                    candidate_id
                    for candidate_id in plan.selected_candidate_ids
                    if candidate_id in by_id
                ]

            slots = wave_size
            for item in reusable:
                if slots <= 0:
                    break
                if item.assessment.cluster_id in self.claim_clusters.get(claim_id, set()):
                    continue
                self.bind(item.candidate.id, claim_id, item)
                slots -= 1
            for candidate_id in fresh_selected:
                if slots <= 0:
                    break
                item = by_id[candidate_id]
                if item.assessment.cluster_id in self.claim_clusters.get(claim_id, set()):
                    continue
                self.bind(candidate_id, claim_id, item)
                if candidate_id not in self.physical_ids:
                    self.physical_ids.add(candidate_id)
                    self.physical.append(
                        {
                            "candidate_id": candidate_id,
                            "claim_id": claim_id,
                            "cluster_id": item.assessment.cluster_id,
                            "source_role": item.assessment.source_role,
                        }
                    )
                slots -= 1

    def build(
        self, ordered_claims: Sequence[ResearchClaim]
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        critical = [claim.id for claim in ordered_claims if claim.priority == "critical"]
        major = [claim.id for claim in ordered_claims if claim.priority == "major"]
        self.schedule(critical, 1)
        self.schedule(critical, 2)
        self.schedule(major, 1)
        conflict_claims = [
            claim.id
            for claim in ordered_claims
            if claim.priority != "context"
            and (
                claim.id in self.open_conflict_claim_ids
                or any(
                    "new_contradiction" in item.assessment.expected_gain_signals
                    for item in self.rankings.get(claim.id, ())
                )
            )
        ]
        self.schedule(conflict_claims, self.reserve, allow_reserve=True)
        read_cap = max(0, self.state.budget.max_reads - self.state.budget.reads_used)
        return self.physical[:read_cap], self.targets
