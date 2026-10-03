"""§164-C1: production-inert shadow read of the durable learner model.

The observer runs *beside* a chat turn, never inside it. It reads the durable
learner model only through the existing ``LearnerModelSnapshot`` projection
rather than reaching into the truth tables, compares it with the legacy state
mechanically, and emits a parity observation into its own namespace.

Two hard properties:

- **production-inert**: nothing here is an input to planning, prompt building,
  retrieval, next-step selection or closure. A turn that shadows must behave
  exactly like a turn that does not.
- **fail-open**: any failure in this module - a missing snapshot, a projection
  error, a classifier error, a collector error - becomes a status on the
  observation. It never raises into the chat path.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.domain.learner_state_parity import (
    DurableLearnerProjection,
    LearnerStateParityObservation,
    LegacyLearnerProjection,
    PARITY_NAMESPACE,
    SHADOW_ERROR,
    SHADOW_OK,
    SHADOW_UNAVAILABLE,
    classify_parity,
)

OBSERVER_VERSION = "learner-state-parity-observer-v1"

# The legacy projection reads only the turn-scoped state object.
_CONFIRMED_STATUS = "confirmed"


def build_legacy_projection(
    learning_state: object,
    *,
    misconception_labels: Sequence[str] = (),
    next_step_hint: str = "",
) -> LegacyLearnerProjection:
    """Neutral view of the legacy turn state. No durable access."""
    return LegacyLearnerProjection(
        objective=str(getattr(learning_state, "objective", "") or ""),
        protocol=str(getattr(learning_state, "protocol", "") or ""),
        known_points=tuple(
            str(point) for point in (getattr(learning_state, "confirmed_points", ()) or ())
        ),
        unresolved_gap=str(getattr(learning_state, "unresolved_gap", "") or ""),
        misconception_labels=tuple(str(item) for item in misconception_labels if str(item).strip()),
        next_step_hint=str(next_step_hint or ""),
        freshness_present=False,
    )


def build_durable_projection(snapshot: object) -> DurableLearnerProjection:
    """Neutral view built **only** from ``LearnerModelSnapshot``.

    Reaching past the snapshot into ``learning_*`` tables would create a second
    durable interpretation path, which is exactly what 164 forbids.
    """
    claim_states = tuple(getattr(snapshot, "claim_states", ()) or ())
    confirmed = tuple(
        str(getattr(claim, "claim_id", "") or "")
        for claim in claim_states
        if str(getattr(claim, "understanding_status", "") or "") == _CONFIRMED_STATUS
    )
    return DurableLearnerProjection(
        goal_id=str(getattr(snapshot, "goal_id", "") or ""),
        objective=str(getattr(snapshot, "objective", "") or ""),
        confirmed_points=tuple(point for point in confirmed if point),
        unresolved_count=int(getattr(snapshot, "unresolved_count", 0) or 0),
        # The durable misconception lifecycle does not exist yet (168).
        misconception_labels=(),
        next_steps=(),
        freshness_present=True,
    )


def observe_learner_state_parity(
    *,
    thread_id: str,
    turn_id: str,
    learning_state: object,
    snapshot: object | None,
    legacy_misconceptions: Sequence[str] = (),
    legacy_next_step_hint: str = "",
    provenance: Mapping[str, object] | None = None,
) -> LearnerStateParityObservation:
    """Emit one parity observation. Never raises; never influences the turn."""
    base_provenance: dict[str, object] = {
        "observer_version": OBSERVER_VERSION,
        "namespace": PARITY_NAMESPACE,
        "read_path": "learner_model_snapshot",
        "semantic_comparator": "none",
    }
    base_provenance.update(provenance or {})

    if snapshot is None:
        return LearnerStateParityObservation(
            thread_id=thread_id,
            turn_id=turn_id,
            shadow_status=SHADOW_UNAVAILABLE,
            legacy_projection_hash="",
            durable_projection_hash="",
            dimensions=(),
            overall_classification="",
            expected_divergences=(),
            conflicts=(),
            provenance=base_provenance,
        )

    try:
        legacy = build_legacy_projection(
            learning_state,
            misconception_labels=legacy_misconceptions,
            next_step_hint=legacy_next_step_hint,
        )
        durable = build_durable_projection(snapshot)
        result = classify_parity(legacy, durable)
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        failed = dict(base_provenance)
        failed["shadow_error"] = type(exc).__name__
        return LearnerStateParityObservation(
            thread_id=thread_id,
            turn_id=turn_id,
            shadow_status=SHADOW_ERROR,
            legacy_projection_hash="",
            durable_projection_hash="",
            dimensions=(),
            overall_classification="",
            expected_divergences=(),
            conflicts=(),
            provenance=failed,
        )

    return LearnerStateParityObservation(
        thread_id=thread_id,
        turn_id=turn_id,
        shadow_status=SHADOW_OK,
        legacy_projection_hash=result.legacy_projection_hash,
        durable_projection_hash=result.durable_projection_hash,
        dimensions=result.dimensions,
        overall_classification=result.overall_classification,
        expected_divergences=result.expected_divergences,
        conflicts=result.conflicts,
        provenance=base_provenance,
    )


class LearnerStateParityCollector:
    """In-memory evidence store in its own namespace.

    Deliberately not backed by the durable learner tables: measuring the
    migration must not pollute the system being measured.
    """

    namespace = PARITY_NAMESPACE

    def __init__(self) -> None:
        self._observations: list[LearnerStateParityObservation] = []

    def record(self, observation: LearnerStateParityObservation) -> None:
        self._observations.append(observation)

    def observations(self) -> tuple[LearnerStateParityObservation, ...]:
        return tuple(self._observations)

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for observation in self._observations:
            key = observation.overall_classification or observation.shadow_status
            counts[key] = counts.get(key, 0) + 1
        return {
            "namespace": self.namespace,
            "total": len(self._observations),
            "by_classification": counts,
            "conflict_turns": sum(
                1 for item in self._observations if item.conflicts
            ),
        }

    def clear(self) -> None:
        self._observations.clear()
