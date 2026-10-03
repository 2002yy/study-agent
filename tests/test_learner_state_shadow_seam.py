"""§164-C1b-1: the seam is flag-gated, hash-first, dead-end and fail-open."""

from __future__ import annotations

import ast
from hashlib import sha256
import json
from pathlib import Path

import pytest

from src.application import learner_state_shadow_seam as seam
from src.application.learner_state_parity_observer import LearnerStateParityCollector
from src.application.learner_state_shadow_seam import (
    DecisionInputHashes,
    build_decision_input_hashes,
    canonical_hash,
    observe_shadow_for_turn,
    publish_shadow_observation,
    shadow_read_enabled,
)
from src.application.shadow_isolation import BestEffortTelemetry
from src.domain.learner_model import LearnerClaimState, LearnerModelSnapshot
from src.pedagogy.types import LearningState

ROOT = Path(__file__).resolve().parents[1]
CHAT_SERVICE = ROOT / "src/application/chat_service.py"
SEAM = ROOT / "src/application/learner_state_shadow_seam.py"


@pytest.fixture(autouse=True)
def _flag_off(monkeypatch):
    monkeypatch.delenv(seam.SHADOW_FLAG, raising=False)
    yield


def _snapshot() -> LearnerModelSnapshot:
    return LearnerModelSnapshot(
        thread_id="thread-1",
        goal_id="goal-1",
        objective="understand hashmap",
        claim_states=(LearnerClaimState("c1", "r1", "fact", "confirmed", "pass"),),
    )


def _hashes() -> DecisionInputHashes:
    return build_decision_input_hashes(
        route={"role": "tutor", "mode": "socratic"},
        pedagogy_plan={"protocol": "socratic_rediscovery"},
        retrieval_plan={"private_query": "hashmap"},
        messages=[{"role": "user", "content": "why hashmap?"}],
    )


# ------------------------------------------------------------------- the flag

def test_flag_defaults_to_off() -> None:
    assert shadow_read_enabled() is False


def test_flag_turns_on_only_for_explicit_truthy_values(monkeypatch) -> None:
    for value in ("1", "true", "ON", "yes"):
        monkeypatch.setenv(seam.SHADOW_FLAG, value)
        assert shadow_read_enabled() is True
    for value in ("0", "false", "off", "", "maybe"):
        monkeypatch.setenv(seam.SHADOW_FLAG, value)
        assert shadow_read_enabled() is False


# ------------------------------------------------- decision-input hashes first

def test_hashes_are_deterministic_and_cover_the_four_inputs() -> None:
    first, second = _hashes(), _hashes()
    assert first.to_dict() == second.to_dict()
    assert set(first.to_dict()) == {
        "route_hash", "pedagogy_plan_hash", "retrieval_plan_hash", "prompt_context_hash",
    }


def test_prompt_context_hash_changes_when_the_prompt_changes() -> None:
    base = build_decision_input_hashes(
        route={}, pedagogy_plan={}, retrieval_plan={},
        messages=[{"role": "user", "content": "a"}],
    )
    changed = build_decision_input_hashes(
        route={}, pedagogy_plan={}, retrieval_plan={},
        messages=[{"role": "user", "content": "b"}],
    )
    assert base.prompt_context_hash != changed.prompt_context_hash


def test_hashes_are_passed_in_not_rebuilt_by_the_observer() -> None:
    """The observer receives the hashes as an argument, so it cannot influence them."""
    signature = observe_shadow_for_turn.__code__.co_varnames
    assert "decision_inputs" in signature
    source = SEAM.read_text(encoding="utf-8")
    # The observer must not recompute the hashes from live planning objects.
    body = source[source.index("def observe_shadow_for_turn"):]
    assert "build_decision_input_hashes(" not in body


# ------------------------------------------------------------------ dead end

def test_observe_returns_a_result_and_never_raises() -> None:
    result = observe_shadow_for_turn(
        thread_id="t", turn_id="turn-1",
        learning_state_before=LearningState(objective="understand hashmap"),
        snapshot_reader=_snapshot,
        decision_inputs=_hashes(),
    )
    assert result.enabled is True
    assert result.outcome is not None
    assert result.telemetry_only is True


def test_observe_without_a_reader_is_disabled() -> None:
    result = observe_shadow_for_turn(
        thread_id="t", turn_id="turn-1",
        learning_state_before=LearningState(),
        snapshot_reader=None,
        decision_inputs=_hashes(),
    )
    assert result.enabled is False
    assert result.outcome is None


def test_observe_is_fail_open_when_the_reader_raises() -> None:
    def explode() -> object:
        raise RuntimeError("durable read exploded")

    result = observe_shadow_for_turn(
        thread_id="t", turn_id="turn-1",
        learning_state_before=LearningState(objective="o"),
        snapshot_reader=explode,
        decision_inputs=_hashes(),
    )
    assert result.outcome is not None
    assert result.outcome.ok is False
    assert result.outcome.reason == "RuntimeError"


def test_chat_service_only_assigns_guards_and_publishes_the_shadow_result() -> None:
    """A structural proof that the outcome is a dead end in production code."""
    tree = ast.parse(CHAT_SERVICE.read_text(encoding="utf-8"))
    uses = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "shadow_result"
    ]
    # Assignment, the None-guard, and the publish argument. Nothing else.
    assert len(uses) == 3, [node.lineno for node in uses]

    # The guard may only gate telemetry publishing: every call inside it must be
    # the publish helper, so no business behaviour can depend on the outcome.
    guards = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and any(
            isinstance(inner, ast.Name) and inner.id == "shadow_result"
            for inner in ast.walk(node.test)
        )
    ]
    assert len(guards) == 1
    calls_inside = [
        inner for inner in ast.walk(guards[0])
        if isinstance(inner, ast.Call)
    ]
    names = {
        call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
        for call in calls_inside
    }
    assert names == {"publish_shadow_observation"}, names

    source = CHAT_SERVICE.read_text(encoding="utf-8")
    for forbidden in ("shadow_result.status", "shadow_result.outcome", "shadow_result.value"):
        assert forbidden not in source, forbidden


# ------------------------------------------------------- publish is best effort

def test_publish_is_non_blocking_and_lands_after_persistence() -> None:
    collector = LearnerStateParityCollector()
    telemetry = BestEffortTelemetry(collector)
    result = observe_shadow_for_turn(
        thread_id="t", turn_id="turn-1",
        learning_state_before=LearningState(objective="understand hashmap"),
        snapshot_reader=_snapshot,
        decision_inputs=_hashes(),
    )
    publish_shadow_observation(
        result, telemetry=telemetry, turn_start_persistence_confirmed=True
    )
    assert telemetry.flush(timeout=1.0) is True
    recorded = collector.observations()
    assert len(recorded) == 1
    assert recorded[0]["turn_start_persistence_confirmed"] is True
    assert "decision_inputs" in recorded[0]
    telemetry.close()


def test_publish_labels_the_start_state_not_the_whole_turn() -> None:
    collector = LearnerStateParityCollector()
    telemetry = BestEffortTelemetry(collector)
    result = observe_shadow_for_turn(
        thread_id="t", turn_id="turn-1",
        learning_state_before=LearningState(objective="o"),
        snapshot_reader=_snapshot,
        decision_inputs=_hashes(),
    )
    publish_shadow_observation(
        result, telemetry=telemetry, turn_start_persistence_confirmed=False
    )
    telemetry.flush(timeout=1.0)
    payload = collector.observations()[0]
    assert payload["turn_start_persistence_confirmed"] is False
    assert "production_turn_commit" not in json.dumps(payload)
    telemetry.close()


def test_publish_never_raises_without_telemetry_or_on_failure() -> None:
    result = observe_shadow_for_turn(
        thread_id="t", turn_id="turn-1",
        learning_state_before=LearningState(objective="o"),
        snapshot_reader=_snapshot,
        decision_inputs=_hashes(),
    )
    publish_shadow_observation(
        result, telemetry=None, turn_start_persistence_confirmed=True
    )

    class BrokenSink:
        def record(self, observation: object) -> None:
            raise RuntimeError("collector down")

    telemetry = BestEffortTelemetry(BrokenSink())
    publish_shadow_observation(
        result, telemetry=telemetry, turn_start_persistence_confirmed=True
    )
    telemetry.close()


def test_canonical_hash_is_stable_and_order_independent() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert len(canonical_hash({"a": 1})) == 64
    assert canonical_hash({"a": 1}) == sha256(
        json.dumps({"a": 1}, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
