"""§164.36 StudyContext comparison experiment (harness-local prototype).

Compares two ways of getting durable truth into the pedagogy planner over the same real
inputs:

A (current): legacy LearningState + durable adjudication -> effective LearningState
B (candidate): legacy LearningState + LearnerModelSnapshot -> transient StudyContext
               -> projection for the planner

The prototype is local to this harness; nothing in production changes. The experiment
answers whether B reduces adapter branches and authority special cases, keeps or improves
the planner decision, can carry ResearchBrief naturally, and does not add more code.

Decision criteria (frozen in 164.36): switch only if B clearly reduces complexity.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from src.application.learner_state_durable_adapter import adjudicate
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.types import LearningState


@dataclass
class StudyContext:
    """Minimal transient read model: carries BOTH representations, no coercion."""

    objective: str = ""
    objective_source: str = ""
    legacy_known_points: tuple[str, ...] = ()
    durable_claim_ids: tuple[str, ...] = ()
    next_step: str = ""
    misconceptions: tuple[str, ...] = ()
    research_brief: object | None = None
    provenance: dict[str, object] = field(default_factory=dict)

    def to_planner_state(self) -> LearningState:
        """Projection for the existing planner: legacy-shaped, durable objective preferred."""
        return LearningState(
            protocol="socratic_rediscovery",
            objective=self.objective,
            confirmed_points=self.legacy_known_points,
            unresolved_gap=self.next_step,
            payload={"durable_claim_ids": list(self.durable_claim_ids)},
        )


def build_a(legacy: LearningState, snapshot: object) -> LearningState:
    return adjudicate(legacy, snapshot).state


def build_b(legacy: LearningState, snapshot: object) -> StudyContext:
    objective = str(getattr(snapshot, "objective", "") or "").strip()
    claims = tuple(
        str(getattr(c, "claim_id", ""))
        for c in (getattr(snapshot, "claim_states", ()) or ())
    )
    return StudyContext(
        objective=objective or legacy.objective,
        objective_source="durable" if objective else "legacy",
        legacy_known_points=tuple(legacy.confirmed_points),
        durable_claim_ids=tuple(c for c in claims if c),
        next_step=legacy.unresolved_gap,
        misconceptions=(),
        provenance={"read_path": "learner_model_snapshot", "adapter": "study_context"},
    )


def _snapshot(objective: str, claim_ids: tuple[str, ...]):
    return SimpleNamespace(
        thread_id="t",
        objective=objective,
        claim_states=tuple(
            SimpleNamespace(claim_id=c, understanding_status="confirmed") for c in claim_ids
        ),
        goal_id="g",
        topic_id="tp",
        goal_status="active",
        unresolved_count=len(claim_ids),
    )


CASES = (
    ("durable-objective + claims", "recover durable resume", "recover session recovery", ("c1", "c2")),
    ("durable-objective only", "recover durable resume", "recover session recovery", ()),
    ("no durable objective", "recover durable resume", "", ("c1",)),
    ("equal objectives", "recover durable resume", "recover durable resume", ("c1",)),
)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("study_context.json")
    engine = PedagogyEngine()
    rows = []
    for name, legacy_obj, durable_obj, claims in CASES:
        legacy = LearningState(
            protocol="socratic_rediscovery",
            objective=legacy_obj,
            confirmed_points=("durable resume",),
            unresolved_gap="why does recovery span turns",
        )
        snap = _snapshot(durable_obj, claims)
        a_state = build_a(legacy, snap)
        b_ctx = build_b(legacy, snap)
        a_plan, _ = engine.plan(user_input="explain recovery", mode="socratic", state=a_state)
        b_plan, _ = engine.plan(
            user_input="explain recovery", mode="socratic", state=b_ctx.to_planner_state()
        )
        a_move = getattr(a_plan, "move", None) or str(a_plan.to_dict().get("move"))
        b_move = getattr(b_plan, "move", None) or str(b_plan.to_dict().get("move"))
        rows.append(
            {
                "case": name,
                "A_effective_objective": a_state.objective,
                "B_effective_objective": b_ctx.objective,
                "B_objective_source": b_ctx.objective_source,
                "A_planner_move": a_move,
                "B_planner_move": b_move,
                "planner_agrees": a_move == b_move,
                # Information A must discard (identifier/text mismatch), B keeps both.
                "A_understanding_comparable": bool(a_state.confirmed_points)
                and a_state.confirmed_points != ("durable resume",),
                "B_carries_durable_claim_ids": len(b_ctx.durable_claim_ids),
                "B_carries_legacy_points": len(b_ctx.legacy_known_points),
                "B_can_attach_research_brief": hasattr(b_ctx, "research_brief"),
            }
        )
    payload = {
        "schema_version": "study-context-comparison-v1",
        "contract": "164.36",
        "note": "harness-local prototype; no production change",
        "case_count": len(rows),
        "planner_agreement": sum(1 for r in rows if r["planner_agrees"]),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        print(
            f"{r['case']}: A={r['A_planner_move']} B={r['B_planner_move']} "
            f"agree={r['planner_agrees']} | B carries claims={r['B_carries_durable_claim_ids']} "
            f"points={r['B_carries_legacy_points']} brief={r['B_can_attach_research_brief']}"
        )
    print("planner agreement:", payload["planner_agreement"], "/", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
