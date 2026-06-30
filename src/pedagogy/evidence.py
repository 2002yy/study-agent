from __future__ import annotations

from dataclasses import dataclass

from src.pedagogy.types import PedagogyTurnPlan


@dataclass(frozen=True)
class DisclosedEvidence:
    context: str = ""
    policy: str = "none"


class EvidenceDisclosurePolicy:
    def select(self, *, context: str, plan: PedagogyTurnPlan) -> DisclosedEvidence:
        clean = context.strip()
        if not clean:
            return DisclosedEvidence()
        if plan.disclosure_level >= 5:
            return DisclosedEvidence(clean, "full")
        if plan.knowledge_kind in {"empirical", "conventional"}:
            return DisclosedEvidence(clean[:2400], "necessary_external_fact")
        if plan.disclosure_level >= 3:
            return DisclosedEvidence(clean[:1600], "bounded_hint")
        # Retrieved answers remain available to the system, but are not injected
        # before the learner has attempted the derivable step.
        return DisclosedEvidence("", "withheld_derivable_answer")
