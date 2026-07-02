from __future__ import annotations

from dataclasses import asdict, dataclass

from src.pedagogy.types import LearningState, PedagogyTurnPlan

WEAK_INPUTS = {
    "不知道",
    "不清楚",
    "不会",
    "没懂",
    "我不知道",
    "我不清楚",
}


@dataclass(frozen=True)
class RetrievalQueryPlan:
    raw_user_input: str
    learning_objective: str
    unresolved_gap: str
    protocol: str
    knowledge_kind: str
    private_query: str
    force_retrieval: bool

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def build_retrieval_query_plan(
    raw_user_input: str,
    *,
    state: LearningState,
    plan: PedagogyTurnPlan,
) -> RetrievalQueryPlan:
    raw = " ".join(raw_user_input.strip().split())
    objective = plan.target_understanding or state.objective
    gap = plan.unresolved_gap or state.unresolved_gap
    weak = raw.replace("。", "").replace("！", "") in WEAK_INPUTS
    parts = [objective, gap]
    if raw and not weak:
        parts.append(raw)
    private_query = " ".join(
        dict.fromkeys(part.strip() for part in parts if part and part.strip())
    )
    if not private_query:
        private_query = raw
    return RetrievalQueryPlan(
        raw_user_input=raw,
        learning_objective=objective,
        unresolved_gap=gap,
        protocol=state.protocol or plan.mode,
        knowledge_kind=plan.knowledge_kind,
        private_query=private_query,
        force_retrieval=bool(objective or gap),
    )
