"""§164-E runtime adjudication surface: G1 objective only (post-165/168 rulings).

G2-G5 are handled by their own owners and are deliberately absent from this surface, so
the tests here assert the objective adjudication, the persistence-plane restore, the
canary opt-in and the fail-open default - and assert that no other gate is emitted.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.application.learner_state_durable_adapter import (
    CANARY_FLAG,
    DURABLE_PREFERRED,
    DURABLE_READ_FLAG,
    GATE_GOAL_OBJECTIVE,
    LEGACY_FALLBACK,
    adjudicate,
    durable_read_enabled,
    restore_persistence_plane,
)
from src.pedagogy.types import LearningState


def _legacy() -> LearningState:
    return LearningState(
        protocol="socratic_rediscovery",
        objective="recover durable resume",
        phase="guided_practice",
        confirmed_points=("durable resume",),
        unresolved_gap="why does recovery span turns",
    )


def _snapshot(*, objective="", claim_ids=()):
    return SimpleNamespace(
        thread_id="t1",
        objective=objective,
        claim_states=tuple(
            SimpleNamespace(claim_id=cid, understanding_status="confirmed")
            for cid in claim_ids
        ),
        goal_id="goal-1",
        topic_id="topic-1",
        goal_status="active",
        unresolved_count=len(claim_ids),
    )


def test_missing_snapshot_leaves_legacy_untouched():
    legacy = _legacy()
    result = adjudicate(legacy, None)
    assert result.state.objective == legacy.objective
    assert result.used_durable is False
    assert result.decisions[0].decision == LEGACY_FALLBACK


def test_durable_objective_is_preferred():
    result = adjudicate(_legacy(), _snapshot(objective="durable owns recovery"))
    assert result.state.objective == "durable owns recovery"
    assert result.used_durable is True
    decision = result.decisions[0]
    assert decision.field == "objective"
    assert decision.gate == GATE_GOAL_OBJECTIVE
    assert decision.decision == DURABLE_PREFERRED


def test_empty_durable_objective_falls_back_to_legacy():
    result = adjudicate(_legacy(), _snapshot(objective=""))
    assert result.state.objective == "recover durable resume"
    assert result.used_durable is False
    assert result.decisions[0].decision == LEGACY_FALLBACK


def test_only_the_objective_gate_is_emitted():
    """G2-G5 must not appear here; they belong to their own owners."""
    result = adjudicate(_legacy(), _snapshot(objective="x", claim_ids=("c1",)))
    gates = {d.gate for d in result.decisions}
    assert gates == {GATE_GOAL_OBJECTIVE}
    assert result.to_dict()["runtime_gates"] == [GATE_GOAL_OBJECTIVE]


def test_legacy_understanding_and_gap_are_not_touched():
    legacy = _legacy()
    result = adjudicate(legacy, _snapshot(objective="x", claim_ids=("c1", "c2")))
    # Durable claim identifiers must not masquerade as legacy text points.
    assert result.state.confirmed_points == legacy.confirmed_points
    assert result.state.unresolved_gap == legacy.unresolved_gap


def test_durable_overlay_does_not_migrate_into_persistence():
    legacy = _legacy()
    adj = adjudicate(legacy, _snapshot(objective="durable owns recovery")).to_dict()
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
    adj = adjudicate(legacy, _snapshot(objective="")).to_dict()
    assert restore_persistence_plane(legacy, legacy, adj) is legacy


def test_durable_read_is_off_by_default(monkeypatch):
    monkeypatch.delenv(DURABLE_READ_FLAG, raising=False)
    monkeypatch.delenv(CANARY_FLAG, raising=False)
    assert durable_read_enabled("t1") is False


def test_canary_enables_only_listed_threads(monkeypatch):
    monkeypatch.delenv(DURABLE_READ_FLAG, raising=False)
    monkeypatch.setenv(CANARY_FLAG, "t1, t2")
    assert durable_read_enabled("t1") is True
    assert durable_read_enabled("t2") is True
    assert durable_read_enabled("t3") is False


def test_global_flag_overrides_canary_scope(monkeypatch):
    monkeypatch.setenv(DURABLE_READ_FLAG, "1")
    monkeypatch.setenv(CANARY_FLAG, "t1")
    assert durable_read_enabled("anything") is True


def test_canary_without_thread_id_is_off(monkeypatch):
    monkeypatch.delenv(DURABLE_READ_FLAG, raising=False)
    monkeypatch.setenv(CANARY_FLAG, "t1")
    assert durable_read_enabled(None) is False
