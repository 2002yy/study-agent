"""§164-E: explicit per-field adjudication between durable and legacy learner state.

This module is the adapter the cutover needs. It is deliberately **additive and
unwired**: nothing in the chat runtime calls it yet, so writing it changes no
behaviour and does not trigger the authority-switch regression gate.

Why an adapter rather than a field assignment: the durable snapshot and the legacy
state are not field-compatible.

* ``objective``            maps directly (str -> str) and durable is preferred.
* ``goal_id`` / ``topic_id`` / ``goal_status`` / ``confirmed_profile`` are durable
  metadata with no legacy counterpart; they go to the payload, not to a legacy field.
* ``claim_states[].claim_id`` cannot become legacy ``confirmed_points`` (identifiers
  versus text), and ``unresolved_count`` (int) cannot become ``unresolved_gap`` (str).

For those last two the adjudication is **not** to coerce them into looking equal:
per §163 F6 (mastery is deliberately unrepresentable) and §164.6/§164.7, the
projection layer deliberately reports them as not comparable, and this adapter must
preserve that. Where a durable value cannot be represented in the legacy shape, the
legacy value is kept and the decision is recorded as an expected divergence rather
than silently overwritten.

The decision vocabulary mirrors the pre-registered §164.29 gate (G1-G5) so the
caller can route differences to telemetry or test evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from src.pedagogy.types import LearningState

DURABLE_READ_FLAG = "LEARNER_STATE_DURABLE_READ"


def durable_read_enabled() -> bool:
    """Phase 2 is opt-in: default OFF keeps production behaviour unchanged."""
    return os.environ.get(DURABLE_READ_FLAG, "0").strip().lower() in {"1", "true", "yes", "on"}


# Decisions (frozen vocabulary; mirrors the §164.29 pre-registered gate).
DURABLE_PREFERRED = "durable_preferred"
LEGACY_FALLBACK = "legacy_fallback"
NOT_COMPARABLE = "not_comparable"
EXPECTED_DIVERGENCE = "expected_divergence"

# Gate ids from §164.29, recorded so routing matches the frozen contract.
GATE_GOAL_OBJECTIVE = "G1"
GATE_UNDERSTANDING = "G2"
GATE_NEXT_STEP = "G3"
GATE_MISCONCEPTION = "G4"
GATE_FRESHNESS = "G5"


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
    """The merged state plus the per-field provenance the caller routes on."""

    state: LearningState
    decisions: tuple[FieldDecision, ...] = ()
    used_durable: bool = False

    def divergences(self) -> tuple[FieldDecision, ...]:
        return tuple(
            d
            for d in self.decisions
            if d.decision in {NOT_COMPARABLE, EXPECTED_DIVERGENCE, LEGACY_FALLBACK}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_durable": self.used_durable,
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
    """Merge durable learner truth into the legacy state shape, field by field.

    Never raises. A missing or empty snapshot leaves the legacy state untouched and
    records why. The returned state is always a valid ``LearningState``.
    """
    decisions: list[FieldDecision] = []
    data = dict(legacy_state.to_dict())

    if snapshot is None:
        decisions.append(
            FieldDecision(
                field="*",
                gate=GATE_GOAL_OBJECTIVE,
                decision=LEGACY_FALLBACK,
                reason="no durable snapshot available",
            )
        )
        return AdjudicationResult(state=legacy_state, decisions=tuple(decisions))

    # --- G1 goal/objective: durable preferred when substantive ----------------
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

    # --- durable metadata with no legacy counterpart -> payload --------------
    payload = dict(data.get("payload") or {})
    for key in ("goal_id", "topic_id", "goal_status"):
        value = _text(getattr(snapshot, key, ""))
        if value:
            payload.setdefault(f"durable_{key}", value)
    if payload:
        data["payload"] = payload

    # --- G2 understanding: identifiers cannot become text points -------------
    claim_states = tuple(getattr(snapshot, "claim_states", ()) or ())
    durable_claim_ids = tuple(
        _text(getattr(claim, "claim_id", "")) for claim in claim_states
    )
    durable_claim_ids = tuple(cid for cid in durable_claim_ids if cid)
    if durable_claim_ids:
        decisions.append(
            FieldDecision(
                field="confirmed_points",
                gate=GATE_UNDERSTANDING,
                decision=NOT_COMPARABLE,
                durable_value=durable_claim_ids,
                legacy_value=tuple(legacy_state.confirmed_points),
                reason=(
                    "durable confirmed understanding is expressed as claim ids, "
                    "which cannot become legacy text points; not coerced"
                ),
            )
        )
    else:
        decisions.append(
            FieldDecision(
                field="confirmed_points",
                gate=GATE_UNDERSTANDING,
                decision=EXPECTED_DIVERGENCE,
                legacy_value=tuple(legacy_state.confirmed_points),
                reason="durable model confirms no understanding (163 F6)",
            )
        )

    # --- G3/G4 next step and misconception: no durable lifecycle yet ---------
    decisions.append(
        FieldDecision(
            field="next_step",
            gate=GATE_NEXT_STEP,
            decision=LEGACY_FALLBACK,
            legacy_value=legacy_state.unresolved_gap,
            reason="durable next-step lifecycle not implemented",
        )
    )
    decisions.append(
        FieldDecision(
            field="misconception",
            gate=GATE_MISCONCEPTION,
            decision=LEGACY_FALLBACK,
            reason="durable misconception lifecycle not implemented (168)",
        )
    )

    # --- G5 freshness: durable-only concept, never blocks -------------------
    decisions.append(
        FieldDecision(
            field="freshness",
            gate=GATE_FRESHNESS,
            decision=EXPECTED_DIVERGENCE,
            reason="freshness is durable-only; legacy has no such concept",
        )
    )

    used_durable = any(d.decision == DURABLE_PREFERRED for d in decisions)
    return AdjudicationResult(
        state=LearningState.from_dict(data),
        decisions=tuple(decisions),
        used_durable=used_durable,
    )
