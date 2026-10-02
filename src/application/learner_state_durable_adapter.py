"""§164-E runtime adjudication between durable and legacy learner state.

**Wired and live** (this module is called by ``ChatService.start_turn`` behind the
opt-in flag; an earlier revision of this docstring said "unwired", which is obsolete).

Scope after the §165 / §168 rulings: the **runtime adjudication surface is G1 only**.
The final rulings were

* G1 objective      -> runtime override (durable preferred, legacy fallback)
* G2 understanding  -> heterogeneous representations, not comparable
* G3 next step      -> coexistence (two distinct dimensions)
* G4 misconception  -> observation vs durable truth (promotion / validation)
* G5 freshness      -> durable-only

so only the objective is genuinely adjudicated into the effective runtime state. The other
four are handled by their own owners and are deliberately **not** emitted here:

* G2 / G3 / G4 -> independent comparators (``run_next_step_parity_probe``,
  ``run_misconception_parity_probe``) and the durable lifecycle services.
* G5 freshness  -> the durable projection.

Emitting them as ``legacy_fallback`` from here produced telemetry that contradicted the
frozen rulings once the lifecycles landed, so that is removed rather than carried.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.pedagogy.types import LearningState

DURABLE_READ_FLAG = "LEARNER_STATE_DURABLE_READ"
CANARY_FLAG = "LEARNER_STATE_DURABLE_READ_CANARY"


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def durable_read_enabled(thread_id: str | None = None) -> bool:
    """Phase 2 is opt-in; default OFF keeps production behaviour unchanged.

    164-E controlled deployment has two explicit opt-ins, neither of which is a global
    default:

    * ``LEARNER_STATE_DURABLE_READ`` - stage-gate enablement, all threads.
    * ``LEARNER_STATE_DURABLE_READ_CANARY`` - a comma-separated thread allowlist, so the
      read is enabled for designated threads only.

    With neither set the read is off, which is the default.
    """

    if _truthy(os.environ.get(DURABLE_READ_FLAG, "0")):
        return True
    allowlist = os.environ.get(CANARY_FLAG, "")
    if not allowlist.strip() or thread_id is None:
        return False
    return thread_id.strip() in {
        item.strip() for item in allowlist.split(",") if item.strip()
    }


# Decisions (frozen vocabulary).
DURABLE_PREFERRED = "durable_preferred"
LEGACY_FALLBACK = "legacy_fallback"

# The only gate the runtime adjudicates. G2-G5 belong to their own owners (see module
# docstring) and are intentionally absent from this surface.
GATE_GOAL_OBJECTIVE = "G1"


@dataclass(frozen=True)
class FieldDecision:
    """One field's adjudication, with the gate it answers to."""

    field: str
    gate: str
    decision: str
    durable_value: Any = None
    legacy_value: Any = None
    reason: str = ""


@dataclass(frozen=True)
class AdjudicationResult:
    """The effective runtime state plus the per-field provenance."""

    state: LearningState
    decisions: tuple[FieldDecision, ...] = ()
    used_durable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_durable": self.used_durable,
            "runtime_gates": [GATE_GOAL_OBJECTIVE],
            "decisions": [
                {
                    "field": d.field,
                    "gate": d.gate,
                    "decision": d.decision,
                    "reason": d.reason,
                }
                for d in self.decisions
            ],
        }


def _text(value: object) -> str:
    return str(value or "").strip()


def adjudicate(
    legacy_state: LearningState,
    snapshot: object | None,
) -> AdjudicationResult:
    """Resolve the effective runtime learner state. Never raises.

    Only the objective is adjudicated (G1). A missing or empty durable objective leaves
    the legacy value in place, and the decision is recorded either way.
    """

    decisions: list[FieldDecision] = []
    data = dict(legacy_state.to_dict())

    if snapshot is None:
        decisions.append(
            FieldDecision(
                field="objective",
                gate=GATE_GOAL_OBJECTIVE,
                decision=LEGACY_FALLBACK,
                reason="no durable snapshot available",
            )
        )
        return AdjudicationResult(state=legacy_state, decisions=tuple(decisions))

    durable_objective = _text(getattr(snapshot, "objective", ""))
    if durable_objective:
        data["objective"] = durable_objective
        decisions.append(
            FieldDecision(
                field="objective",
                gate=GATE_GOAL_OBJECTIVE,
                decision=DURABLE_PREFERRED,
                durable_value=durable_objective,
                legacy_value=legacy_state.objective,
            )
        )
    else:
        decisions.append(
            FieldDecision(
                field="objective",
                gate=GATE_GOAL_OBJECTIVE,
                decision=LEGACY_FALLBACK,
                legacy_value=legacy_state.objective,
                reason="durable objective empty",
            )
        )

    used_durable = any(d.decision == DURABLE_PREFERRED for d in decisions)
    return AdjudicationResult(
        state=LearningState.from_dict(data),
        decisions=tuple(decisions),
        used_durable=used_durable,
    )


def restore_persistence_plane(
    next_state: LearningState,
    legacy_state: LearningState,
    adjudication: dict[str, object] | None,
) -> LearningState:
    """Keep the legacy persistence plane free of the durable overlay.

    Phase 2 may let the durable value drive this turn's effective state, but it must not
    migrate silently into legacy persistence. Any field the adjudication took from durable
    is restored to its legacy value in the state that is about to be persisted.
    """

    if not adjudication:
        return next_state
    raw_decisions = adjudication.get("decisions")
    decisions: list[object] = (
        raw_decisions if isinstance(raw_decisions, list) else []
    )
    taken = {
        str(d.get("field"))
        for d in decisions
        if isinstance(d, dict) and d.get("decision") == DURABLE_PREFERRED
    }
    if not taken:
        return next_state
    data = dict(next_state.to_dict())
    if "objective" in taken:
        data["objective"] = legacy_state.objective
    return LearningState.from_dict(data)
