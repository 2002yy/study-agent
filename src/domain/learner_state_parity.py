"""§164-C0/C1: neutral parity projections and their deterministic classifier.

These projections exist **only** to measure migration between the legacy
turn-scoped learning state and the durable learner model. They are not a third
learner-state authority and must never be read by a chat turn as context.

The classifier is deliberately mechanical: exact/canonical identity and linkage
only. There is no LLM semantic comparator here, because introducing one would
recreate exactly the automatic semantic judge that §162 disqualified. Anything
the rules cannot decide is reported as ``NOT_COMPARABLE`` instead of guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

# Classification vocabulary (164.10). Never a boolean.
MATCH = "MATCH"
COMPATIBLE = "COMPATIBLE"
EXPECTED_DIVERGENCE = "EXPECTED_DIVERGENCE"
MISSING_LEGACY = "MISSING_LEGACY"
MISSING_DURABLE = "MISSING_DURABLE"
CONFLICT = "CONFLICT"
NOT_COMPARABLE = "NOT_COMPARABLE"

# next_step uses three extra labels: the two sides produce next steps through
# different paths, so a one-sided or differing proposal is not automatically a
# defect.
LEGACY_ONLY = "LEGACY_ONLY"
DURABLE_ONLY = "DURABLE_ONLY"
EXPLAINED_DIVERGENCE = "EXPLAINED_DIVERGENCE"

CLASSIFICATIONS: tuple[str, ...] = (
    MATCH, COMPATIBLE, EXPECTED_DIVERGENCE,
    MISSING_LEGACY, MISSING_DURABLE, CONFLICT, NOT_COMPARABLE,
)

DIMENSION_GOAL_OBJECTIVE = "goal_objective"
DIMENSION_UNDERSTANDING = "understanding"
DIMENSION_NEXT_STEP = "next_step"
DIMENSION_MISCONCEPTION = "misconception"
DIMENSION_FRESHNESS = "freshness"

DIMENSIONS: tuple[str, ...] = (
    DIMENSION_GOAL_OBJECTIVE, DIMENSION_UNDERSTANDING, DIMENSION_NEXT_STEP,
    DIMENSION_MISCONCEPTION, DIMENSION_FRESHNESS,
)

SHADOW_OK = "ok"
SHADOW_UNAVAILABLE = "unavailable"
SHADOW_ERROR = "error"

PARITY_NAMESPACE = "learner_state_parity_observations"


def _canonical_text(value: str) -> str:
    """Casefold, strip punctuation and collapse whitespace for identity checks."""
    cleaned = re.sub(r"[^\w\s]", " ", str(value).casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class LegacyLearnerProjection:
    """Neutral view of the turn-scoped legacy state. Measurement only."""

    objective: str = ""
    protocol: str = ""
    known_points: tuple[str, ...] = ()
    unresolved_gap: str = ""
    misconception_labels: tuple[str, ...] = ()
    next_step_hint: str = ""
    freshness_present: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "protocol": self.protocol,
            "known_points": list(self.known_points),
            "unresolved_gap": self.unresolved_gap,
            "misconception_labels": list(self.misconception_labels),
            "next_step_hint": self.next_step_hint,
            "freshness_present": self.freshness_present,
        }

    def projection_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class DurableLearnerProjection:
    """Neutral view of the durable learner model. Measurement only."""

    goal_id: str = ""
    objective: str = ""
    confirmed_points: tuple[str, ...] = ()
    unresolved_count: int = 0
    misconception_labels: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()
    freshness_present: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "objective": self.objective,
            "confirmed_points": list(self.confirmed_points),
            "unresolved_count": self.unresolved_count,
            "misconception_labels": list(self.misconception_labels),
            "next_steps": list(self.next_steps),
            "freshness_present": self.freshness_present,
        }

    def projection_hash(self) -> str:
        return _hash(self.to_dict())


@dataclass(frozen=True)
class DimensionVerdict:
    dimension: str
    classification: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "classification": self.classification,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SemanticParityResult:
    overall_classification: str
    dimensions: tuple[DimensionVerdict, ...]
    expected_divergences: tuple[str, ...]
    conflicts: tuple[str, ...]
    legacy_projection_hash: str
    durable_projection_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_classification": self.overall_classification,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "expected_divergences": list(self.expected_divergences),
            "conflicts": list(self.conflicts),
            "legacy_projection_hash": self.legacy_projection_hash,
            "durable_projection_hash": self.durable_projection_hash,
        }

    def verdict_for(self, dimension: str) -> DimensionVerdict:
        for item in self.dimensions:
            if item.dimension == dimension:
                return item
        raise KeyError(dimension)


def _classify_goal_objective(
    legacy: LegacyLearnerProjection, durable: DurableLearnerProjection
) -> DimensionVerdict:
    left = _canonical_text(legacy.objective)
    right = _canonical_text(durable.objective)
    if not left and not right:
        return DimensionVerdict(DIMENSION_GOAL_OBJECTIVE, NOT_COMPARABLE, "neither side states an objective")
    if not left:
        return DimensionVerdict(DIMENSION_GOAL_OBJECTIVE, MISSING_LEGACY, "legacy has no objective")
    if not right:
        return DimensionVerdict(DIMENSION_GOAL_OBJECTIVE, MISSING_DURABLE, "durable has no objective")
    if left == right:
        return DimensionVerdict(DIMENSION_GOAL_OBJECTIVE, MATCH)
    if left in right or right in left:
        return DimensionVerdict(
            DIMENSION_GOAL_OBJECTIVE, COMPATIBLE, "same objective at a different granularity"
        )
    return DimensionVerdict(DIMENSION_GOAL_OBJECTIVE, CONFLICT, "objectives name different subjects")


def _classify_understanding(
    legacy: LegacyLearnerProjection, durable: DurableLearnerProjection
) -> DimensionVerdict:
    """The hard gate. Contradiction is a conflict; absence is not."""
    durable_confirmed = {_canonical_text(point) for point in durable.confirmed_points}
    legacy_known = {_canonical_text(point) for point in legacy.known_points}
    gap = _canonical_text(legacy.unresolved_gap)
    durable_confirmed.discard("")
    legacy_known.discard("")

    # A durable confirmation against a legacy gap naming the same point is a
    # real contradiction, not a capability difference.
    if gap and durable_confirmed and any(gap in point or point in gap for point in durable_confirmed):
        return DimensionVerdict(
            DIMENSION_UNDERSTANDING, CONFLICT, "durable confirms what legacy reports as an open gap"
        )
    if durable_confirmed and not legacy_known:
        return DimensionVerdict(
            DIMENSION_UNDERSTANDING, MISSING_LEGACY, "legacy state has no known points"
        )
    if legacy_known and not durable_confirmed:
        return DimensionVerdict(
            DIMENSION_UNDERSTANDING, MISSING_DURABLE, "durable model confirms nothing"
        )
    if not durable_confirmed and not legacy_known:
        return DimensionVerdict(
            DIMENSION_UNDERSTANDING, NOT_COMPARABLE, "neither side carries understanding evidence"
        )
    if durable_confirmed == legacy_known:
        return DimensionVerdict(DIMENSION_UNDERSTANDING, MATCH)
    if durable_confirmed < legacy_known or legacy_known < durable_confirmed:
        return DimensionVerdict(
            DIMENSION_UNDERSTANDING, COMPATIBLE, "one side knows strictly more"
        )
    return DimensionVerdict(
        DIMENSION_UNDERSTANDING, NOT_COMPARABLE, "known sets differ without containment"
    )


def _classify_next_step(
    legacy: LegacyLearnerProjection, durable: DurableLearnerProjection
) -> DimensionVerdict:
    left = _canonical_text(legacy.next_step_hint)
    rights = {_canonical_text(step) for step in durable.next_steps}
    rights.discard("")
    if not left and not rights:
        return DimensionVerdict(DIMENSION_NEXT_STEP, MATCH, "neither side proposes a next step")
    if not left:
        return DimensionVerdict(DIMENSION_NEXT_STEP, DURABLE_ONLY)
    if not rights:
        return DimensionVerdict(DIMENSION_NEXT_STEP, LEGACY_ONLY)
    if left in rights:
        return DimensionVerdict(DIMENSION_NEXT_STEP, MATCH)
    # Phase 1 collects differences; the two paths produce next steps differently,
    # so a difference is not presumed to be a migration bug.
    return DimensionVerdict(
        DIMENSION_NEXT_STEP, EXPLAINED_DIVERGENCE, "different producers, not necessarily a defect"
    )


def _classify_misconception(
    legacy: LegacyLearnerProjection, durable: DurableLearnerProjection
) -> DimensionVerdict:
    left = {_canonical_text(item) for item in legacy.misconception_labels}
    right = {_canonical_text(item) for item in durable.misconception_labels}
    left.discard("")
    right.discard("")
    if not left and not right:
        return DimensionVerdict(DIMENSION_MISCONCEPTION, MATCH, "neither side reports one")
    if left and not right:
        return DimensionVerdict(
            DIMENSION_MISCONCEPTION, EXPECTED_DIVERGENCE,
            "durable misconception lifecycle does not exist yet (168)",
        )
    if right and not left:
        return DimensionVerdict(
            DIMENSION_MISCONCEPTION, EXPECTED_DIVERGENCE, "durable-only misconception record"
        )
    if left == right:
        return DimensionVerdict(DIMENSION_MISCONCEPTION, MATCH)
    if left & right:
        return DimensionVerdict(DIMENSION_MISCONCEPTION, COMPATIBLE, "partially overlapping")
    return DimensionVerdict(
        DIMENSION_MISCONCEPTION, EXPECTED_DIVERGENCE, "disjoint, lifecycle not comparable yet"
    )


def _classify_freshness(
    legacy: LegacyLearnerProjection, durable: DurableLearnerProjection
) -> DimensionVerdict:
    if durable.freshness_present and not legacy.freshness_present:
        return DimensionVerdict(
            DIMENSION_FRESHNESS, EXPECTED_DIVERGENCE, "freshness is durable-only by design"
        )
    if legacy.freshness_present and not durable.freshness_present:
        return DimensionVerdict(DIMENSION_FRESHNESS, MISSING_DURABLE)
    if legacy.freshness_present and durable.freshness_present:
        return DimensionVerdict(DIMENSION_FRESHNESS, MATCH)
    return DimensionVerdict(DIMENSION_FRESHNESS, NOT_COMPARABLE, "neither side carries freshness")


_DIMENSION_CLASSIFIERS = {
    DIMENSION_GOAL_OBJECTIVE: _classify_goal_objective,
    DIMENSION_UNDERSTANDING: _classify_understanding,
    DIMENSION_NEXT_STEP: _classify_next_step,
    DIMENSION_MISCONCEPTION: _classify_misconception,
    DIMENSION_FRESHNESS: _classify_freshness,
}


def _overall(verdicts: tuple[DimensionVerdict, ...]) -> str:
    kinds = {item.classification for item in verdicts}
    if CONFLICT in kinds:
        return CONFLICT
    if NOT_COMPARABLE in kinds:
        return NOT_COMPARABLE
    missing = kinds & {MISSING_LEGACY, MISSING_DURABLE}
    if len(missing) == 1:
        return next(iter(missing))
    if len(missing) > 1:
        return NOT_COMPARABLE
    if EXPECTED_DIVERGENCE in kinds:
        return EXPECTED_DIVERGENCE
    if COMPATIBLE in kinds or DURABLE_ONLY in kinds or LEGACY_ONLY in kinds:
        return COMPATIBLE
    return MATCH


def classify_parity(
    legacy: LegacyLearnerProjection, durable: DurableLearnerProjection
) -> SemanticParityResult:
    """Deterministic, model-free comparison across the five frozen dimensions."""
    verdicts = tuple(
        _DIMENSION_CLASSIFIERS[dimension](legacy, durable) for dimension in DIMENSIONS
    )
    return SemanticParityResult(
        overall_classification=_overall(verdicts),
        dimensions=verdicts,
        expected_divergences=tuple(
            item.dimension for item in verdicts
            if item.classification == EXPECTED_DIVERGENCE
        ),
        conflicts=tuple(
            item.dimension for item in verdicts if item.classification == CONFLICT
        ),
        legacy_projection_hash=legacy.projection_hash(),
        durable_projection_hash=durable.projection_hash(),
    )


@dataclass(frozen=True)
class LearnerStateParityObservation:
    """Migration-measurement evidence. Never durable learner truth."""

    thread_id: str
    turn_id: str
    shadow_status: str
    legacy_projection_hash: str
    durable_projection_hash: str
    dimensions: tuple[DimensionVerdict, ...]
    overall_classification: str
    expected_divergences: tuple[str, ...]
    conflicts: tuple[str, ...]
    provenance: Mapping[str, object]

    @property
    def namespace(self) -> str:
        return PARITY_NAMESPACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "namespace": PARITY_NAMESPACE,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "shadow_status": self.shadow_status,
            "legacy_projection_hash": self.legacy_projection_hash,
            "durable_projection_hash": self.durable_projection_hash,
            "dimensions": [item.to_dict() for item in self.dimensions],
            "overall_classification": self.overall_classification,
            "expected_divergences": list(self.expected_divergences),
            "conflicts": list(self.conflicts),
            "provenance": dict(self.provenance),
        }
