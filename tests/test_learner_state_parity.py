"""§164-C1: parity classification, fail-open shadow read, and inertness proof."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.application.learner_state_parity_observer import (
    LearnerStateParityCollector,
    build_durable_projection,
    build_legacy_projection,
    observe_learner_state_parity,
)
from src.domain.learner_state_parity import (
    COMPATIBLE,
    CONFLICT,
    DIMENSION_FRESHNESS,
    DIMENSION_GOAL_OBJECTIVE,
    DIMENSION_MISCONCEPTION,
    DIMENSION_NEXT_STEP,
    DIMENSION_UNDERSTANDING,
    DIMENSIONS,
    DURABLE_ONLY,
    EXPECTED_DIVERGENCE,
    EXPLAINED_DIVERGENCE,
    LEGACY_ONLY,
    MATCH,
    MISSING_DURABLE,
    MISSING_LEGACY,
    NOT_COMPARABLE,
    PARITY_NAMESPACE,
    SHADOW_ERROR,
    SHADOW_OK,
    SHADOW_UNAVAILABLE,
    DurableLearnerProjection,
    LegacyLearnerProjection,
    classify_parity,
)
from src.domain.learner_model import LearnerClaimState, LearnerModelSnapshot
from src.pedagogy.types import LearningState

ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "src/application/learner_state_parity_observer.py"
PARITY_DOMAIN = ROOT / "src/domain/learner_state_parity.py"


def _classify(legacy: LegacyLearnerProjection, durable: DurableLearnerProjection) -> str:
    return classify_parity(legacy, durable).overall_classification


# ---------------------------------------------------------------- dimensions

def test_goal_objective_granularity_is_compatible_not_conflict() -> None:
    legacy = LegacyLearnerProjection(objective="understand hashmap")
    durable = DurableLearnerProjection(
        objective="understand hashmap equals hashcode and key mutability"
    )
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_GOAL_OBJECTIVE).classification == COMPATIBLE


def test_goal_objective_different_subjects_conflict() -> None:
    legacy = LegacyLearnerProjection(objective="hashmap")
    durable = DurableLearnerProjection(objective="java thread synchronisation")
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_GOAL_OBJECTIVE).classification == CONFLICT
    assert DIMENSION_GOAL_OBJECTIVE in result.conflicts


def test_objective_undecidable_mechanically_is_not_comparable() -> None:
    legacy = LegacyLearnerProjection()
    durable = DurableLearnerProjection()
    assert _classify(legacy, durable) == NOT_COMPARABLE


def test_durable_confirmation_against_legacy_gap_is_a_conflict() -> None:
    legacy = LegacyLearnerProjection(
        objective="hashmap", unresolved_gap="hashcode contract", known_points=("other",),
    )
    durable = DurableLearnerProjection(
        objective="hashmap", confirmed_points=("hashcode contract",),
    )
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_UNDERSTANDING).classification == CONFLICT
    assert DIMENSION_UNDERSTANDING in result.conflicts


def test_durable_confirmation_with_legacy_unknown_is_missing_legacy() -> None:
    legacy = LegacyLearnerProjection(objective="hashmap")
    durable = DurableLearnerProjection(objective="hashmap", confirmed_points=("c1",))
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_UNDERSTANDING).classification == MISSING_LEGACY


def test_legacy_known_without_durable_confirmation_is_missing_durable() -> None:
    legacy = LegacyLearnerProjection(objective="hashmap", known_points=("c1",))
    durable = DurableLearnerProjection(objective="hashmap")
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_UNDERSTANDING).classification == MISSING_DURABLE


def test_identical_known_sets_match() -> None:
    legacy = LegacyLearnerProjection(objective="hashmap", known_points=("c1", "c2"))
    durable = DurableLearnerProjection(objective="hashmap", confirmed_points=("c2", "c1"))
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_UNDERSTANDING).classification == MATCH


def test_next_step_differences_are_collected_not_failed() -> None:
    legacy = LegacyLearnerProjection(
        objective="hashmap", next_step_hint="practise buckets",
    )
    durable = DurableLearnerProjection(
        objective="hashmap", next_steps=("research equals contract",),
    )
    result = classify_parity(legacy, durable)
    verdict = result.verdict_for(DIMENSION_NEXT_STEP)
    assert verdict.classification == EXPLAINED_DIVERGENCE
    assert result.conflicts == ()


def test_next_step_one_sided_is_labelled_by_side() -> None:
    base = LegacyLearnerProjection(objective="hashmap")
    assert classify_parity(
        base, DurableLearnerProjection(objective="hashmap", next_steps=("x",))
    ).verdict_for(DIMENSION_NEXT_STEP).classification == DURABLE_ONLY
    assert classify_parity(
        LegacyLearnerProjection(objective="hashmap", next_step_hint="x"),
        DurableLearnerProjection(objective="hashmap"),
    ).verdict_for(DIMENSION_NEXT_STEP).classification == LEGACY_ONLY


def test_legacy_only_misconception_is_expected_divergence() -> None:
    legacy = LegacyLearnerProjection(
        objective="hashmap", misconception_labels=("thinks keys are compared by identity",),
    )
    durable = DurableLearnerProjection(objective="hashmap")
    result = classify_parity(legacy, durable)
    verdict = result.verdict_for(DIMENSION_MISCONCEPTION)
    assert verdict.classification == EXPECTED_DIVERGENCE
    assert DIMENSION_MISCONCEPTION in result.expected_divergences


def test_freshness_divergence_never_conflicts() -> None:
    legacy = LegacyLearnerProjection(objective="hashmap", known_points=("c1",))
    durable = DurableLearnerProjection(objective="hashmap", confirmed_points=("c1",))
    result = classify_parity(legacy, durable)
    assert result.verdict_for(DIMENSION_FRESHNESS).classification == EXPECTED_DIVERGENCE
    assert result.conflicts == ()


def test_overall_precedence_prefers_conflict_then_not_comparable() -> None:
    conflicting = LegacyLearnerProjection(objective="hashmap", known_points=("c1",))
    durable_conflict = DurableLearnerProjection(
        objective="threads", confirmed_points=("c1",)
    )
    assert _classify(conflicting, durable_conflict) == CONFLICT


def test_classification_is_deterministic() -> None:
    legacy = LegacyLearnerProjection(objective="hashmap", known_points=("c1",))
    durable = DurableLearnerProjection(objective="hashmap", confirmed_points=("c1",))
    first = classify_parity(legacy, durable)
    second = classify_parity(legacy, durable)
    assert first.to_dict() == second.to_dict()
    assert first.overall_classification == EXPECTED_DIVERGENCE


# ------------------------------------------------------------ shadow observer

def _snapshot(**overrides) -> LearnerModelSnapshot:
    base = {
        "thread_id": "thread-1",
        "goal_id": "goal-1",
        "objective": "understand hashmap",
        "claim_states": (
            LearnerClaimState("c1", "r1", "fact", "confirmed", "pass"),
        ),
    }
    base.update(overrides)
    return LearnerModelSnapshot(**base)


def test_shadow_observation_is_recorded_with_its_own_namespace() -> None:
    observation = observe_learner_state_parity(
        thread_id="thread-1",
        turn_id="turn-1",
        learning_state=LearningState(objective="understand hashmap", confirmed_points=("c1",)),
        snapshot=_snapshot(),
    )
    assert observation.shadow_status == SHADOW_OK
    assert observation.namespace == PARITY_NAMESPACE
    payload = observation.to_dict()
    assert payload["namespace"] == "learner_state_parity_observations"
    assert set(payload["dimensions"][0]) == {"dimension", "classification", "detail"}
    assert [item["dimension"] for item in payload["dimensions"]] == list(DIMENSIONS)


def test_missing_snapshot_is_unavailable_and_does_not_raise() -> None:
    observation = observe_learner_state_parity(
        thread_id="t", turn_id="turn", learning_state=LearningState(), snapshot=None,
    )
    assert observation.shadow_status == SHADOW_UNAVAILABLE
    assert observation.overall_classification == ""
    assert observation.dimensions == ()


def test_projection_failure_is_fail_open() -> None:
    class Exploding:
        @property
        def claim_states(self):
            raise RuntimeError("durable read exploded")

    observation = observe_learner_state_parity(
        thread_id="t", turn_id="turn",
        learning_state=LearningState(objective="x"), snapshot=Exploding(),
    )
    assert observation.shadow_status == SHADOW_ERROR
    assert observation.provenance["shadow_error"] == "RuntimeError"
    assert observation.dimensions == ()


def test_durable_projection_reads_only_the_snapshot() -> None:
    projection = build_durable_projection(_snapshot())
    assert projection.confirmed_points == ("c1",)
    assert projection.objective == "understand hashmap"
    assert projection.goal_id == "goal-1"
    # The durable misconception lifecycle does not exist yet.
    assert projection.misconception_labels == ()
    assert projection.freshness_present is True


def test_legacy_projection_reads_only_the_turn_state() -> None:
    projection = build_legacy_projection(
        LearningState(objective="o", protocol="socratic_rediscovery",
                      confirmed_points=("c1",), unresolved_gap="gap"),
        misconception_labels=("m1",), next_step_hint="practise",
    )
    assert projection.objective == "o"
    assert projection.protocol == "socratic_rediscovery"
    assert projection.known_points == ("c1",)
    assert projection.unresolved_gap == "gap"
    assert projection.freshness_present is False


def test_parity_observation_never_reaches_durable_truth_tables() -> None:
    for path in (OBSERVER, PARITY_DOMAIN):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            for token in ("repositories", "sqlite", "learning_truth_repository",
                          "learning_closure", "runtime_repository", "session_service"):
                assert token not in module, f"{path.name}: {module}"


def test_collector_stays_in_its_own_namespace() -> None:
    collector = LearnerStateParityCollector()
    assert collector.namespace == PARITY_NAMESPACE
    collector.record(observe_learner_state_parity(
        thread_id="t", turn_id="turn-1",
        learning_state=LearningState(objective="o"), snapshot=_snapshot(objective="o"),
    ))
    collector.record(observe_learner_state_parity(
        thread_id="t", turn_id="turn-2",
        learning_state=LearningState(objective="o"), snapshot=None,
    ))
    summary = collector.summary()
    assert summary["total"] == 2
    assert summary["namespace"] == PARITY_NAMESPACE
    assert summary["by_classification"][SHADOW_UNAVAILABLE] == 1
    assert "mastery" not in str(summary).lower()


@pytest.mark.parametrize("turn_id", ["turn-a", "turn-b"])
def test_shadow_read_has_no_side_effect_on_the_inputs(turn_id: str) -> None:
    state = LearningState(objective="o", confirmed_points=("c1",))
    snapshot = _snapshot(objective="o")
    before_state, before_snapshot = state.to_dict(), snapshot.to_dict()
    observe_learner_state_parity(
        thread_id="t", turn_id=turn_id, learning_state=state, snapshot=snapshot,
    )
    assert state.to_dict() == before_state
    assert snapshot.to_dict() == before_snapshot
