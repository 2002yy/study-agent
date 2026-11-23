"""Apply the completed physical read to the shared wave results and budget."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.application.research_runtime_read_budget_context import ReadWaveBudgetContext
from src.application.research_runtime_read_projection import project_read_chain
from src.application.research_runtime_source_evidence_context import (
    ReadSourceEvidenceContext,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.web.research.contracts import ResearchState


@dataclass(frozen=True, slots=True)
class ReadWaveResultContext:
    budget: ReadWaveBudgetContext
    source_evidence: ReadSourceEvidenceContext

    def record_chain(
        self,
        *,
        candidate: CandidatePoolItem,
        plan_item: Mapping[str, str],
        chain_steps: Sequence[ChainStepResult],
        source_limit: int,
    ) -> ResearchState:
        """Charge usable text, record its source, then project the current budget."""

        projection = project_read_chain(
            candidate=candidate,
            plan_item=plan_item,
            chain_steps=chain_steps,
            source_limit=source_limit,
        )
        if projection.ok:
            self.budget.quota.charge_read(projection.content)
        self.source_evidence.record_projection(
            projection.record,
            ok=projection.ok,
            canonical_url=candidate.canonical_url,
        )
        return self.budget.project()
