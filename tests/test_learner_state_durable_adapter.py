"""§164-E adapter: per-field durable/legacy adjudication (additive, unwired)."""

from __future__ import annotations

from types import SimpleNamespace

from src.application.learner_state_durable_adapter import (
    restore_persistence_plane,
    DURABLE_PREFERRED,
    EXPECTED_DIVERGENCE,
    GATE_GOAL_OBJECTIVE,
    GATE_UNDERSTANDING,
    LEGACY_FALLBACK,
    NOT_COMPARABLE,
    adjudicate,
)
from src.pedagogy.types import LearningState


def _legacy() -> LearningState:
    return LearningState(
        protocol="socratic_rediscovery",
        objective="recover durable resume",
        phase="guided_practice",
        confirmed_points=("durable resume", "recovery spans turns"),
        unresolved_gap="why does recovery span turns",
    )


def _snapshot(*, objective="", claim_ids=(), goal_id="goal-1", goal_status="active"):
    claims = tuple(
        SimpleNamespace(claim_id=cid, understanding_status="confirmed")
        for cid in claim_ids
    )
    return SimpleNamespace(
        thread_id="t1",
        objective=objective,
        claim_states=claims,
        goal_id=goal_id,
        topic_id="topic-1",
        goal_status=goal_status,
        unresolved_count=len(claim_ids),
    )


def test_missing_snapshot_leaves_legacy_untouched():
    legacy = _legacy()
    result = adjudicate(legacy, None)
    assert result.state.objective == legacy.objective
    assert result.state.confirmed_points == legacy.confirmed_points
    assert result.used_durable is False
    assert result.decisions[0].decision == LEGACY_FALLBACK


def test_durable_objective_is_preferred():
    result = adjudicate(_legacy(), _snapshot(objective="durable owns recovery"))
    assert result.state.objective == "durable owns recovery"
    assert result.used_durable is True
    decision = next(d for d in result.decisions if d.field == "objective")
    assert decision.decision == DURABLE_PREFERRED
    assert decision.gate == GATE_GOAL_OBJECTIVE


def test_empty_durable_objective_falls_back_to_legacy():
    result = adjudicate(_legacy(), _snapshot(objective=""))
    assert result.state.objective == "recover durable resume"
    assert result.used_durable is False
    decision = next(d for d in result.decisions if d.field == "objective")
    assert decision.decision == LEGACY_FALLBACK


def test_durable_claim_ids_are_not_coerced_into_text_points():
    legacy = _legacy()
    result = adjudicate(legacy, _snapshot(claim_ids=("claim-a", "claim-b")))
    # The legacy text points survive: identifiers must not masquerade as text.
    assert result.state.confirmed_points == legacy.confirmed_points
    decision = next(d for d in result.decisions if d.field == "confirmed_points")
    assert decision.decision == NOT_COMPARABLE
    assert decision.gate == GATE_UNDERSTANDING
    assert decision.durable_value == ("claim-a", "claim-b")


def test_no_confirmed_understanding_is_expected_divergence():
    result = adjudicate(_legacy(), _snapshot(claim_ids=()))
    decision = next(d for d in result.decisions if d.field == "confirmed_points")
    assert decision.decision == EXPECTED_DIVERGENCE


def test_durable_metadata_goes_to_payload_not_to_legacy_fields():
    result = adjudicate(_legacy(), _snapshot(objective="x"))
    payload = result.state.payload
    assert payload["durable_goal_id"] == "goal-1"
    assert payload["durable_topic_id"] == "topic-1"
    assert payload["durable_goal_status"] == "active"
    # No legacy field was repurposed for durable metadata.
    assert result.state.objective == "x"


def test_next_step_misconception_and_freshness_decisions_are_recorded():
    result = adjudicate(_legacy(), _snapshot(objective="x"))
    gates = {d.gate: d.decision for d in result.decisions}
    assert gates["G3"] == LEGACY_FALLBACK
    assert gates["G4"] == LEGACY_FALLBACK
    assert gates["G5"] == EXPECTED_DIVERGENCE


def test_divergences_collects_only_non_durable_preferred_decisions():
    result = adjudicate(_legacy(), _snapshot(objective="x", claim_ids=("c1",)))
    fields = {d.field for d in result.divergences()}
    assert "objective" not in fields
    assert "confirmed_points" in fields
    assert "freshness" in fields


def test_result_is_serialisable_for_telemetry():
    result = adjudicate(_legacy(), _snapshot(objective="x", claim_ids=("c1",)))
    as_dict = result.to_dict()
    assert as_dict["used_durable"] is True
    assert {d["field"] for d in as_dict["decisions"]} >= {"objective", "confirmed_points"}


def test_durable_overlay_does_not_migrate_into_persistence():
    legacy = _legacy()
    adj = adjudicate(legacy, _snapshot(objective="durable owns recovery")).to_dict()
    # The planner saw the durable objective; persistence must keep the legacy one.
    next_state = LearningState.from_dict(
        {**legacy.to_dict(), "objective": "durable owns recovery"}
    )
    restored = restore_persistence_plane(next_state, legacy, adj)
    assert restored.objective == legacy.objective


def test_no_adjudication_leaves_persistence_untouched():
    legacy = _legacy()
    assert restore_persistence_plane(legacy, legacy, None) is legacy
    assert restore_persistence_plane(legacy, legacy, {}) is legacy


def test_legacy_fallback_adjudication_leaves_persistence_untouched():
    legacy = _legacy()
    adj = adjudicate(legacy, _snapshot(objective="")).to_dict()  # no durable_preferred
    assert restore_persistence_plane(legacy, legacy, adj) is legacy
