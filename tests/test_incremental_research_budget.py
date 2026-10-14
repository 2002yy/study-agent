"""Experimental policies test accounting; these numbers are not production tuning."""

import copy
import json

import pytest

from src.web.research.incremental_budget import (
    AXES,
    authorize_goal,
    consume,
    initialize_budget,
    load_incremental_policy,
    remaining,
)


def policy():
    return {
        "initial": dict(zip(AXES, [2, 4, 6, 0, 60])),
        "per_goal": dict(zip(AXES, [1, 2, 3, 0, 30])),
        "limits": dict(zip(AXES, [4, 8, 12, 0, 120])),
    }


def test_grant_survives_restore_and_never_resets_consumption():
    deep = {}
    initialize_budget(deep, policy())
    consume(deep, "searches", 3)
    grant = authorize_goal(deep, steering_id="s1", task_id="goal1")
    assert grant["searches"] == 2
    assert remaining(deep, "searches") == 3
    restored = json.loads(json.dumps(deep))
    initialize_budget(restored, policy())
    authorize_goal(restored, steering_id="s1", task_id="goal1")
    assert restored == deep
    assert authorize_goal(restored, steering_id="s2", task_id="goal1") == {}
    assert restored["incremental_budget"]["consumed"]["searches"] == 3


def test_global_caps_are_enforced_across_multiple_requirements():
    deep = {}
    initialize_budget(deep, policy())
    for i in range(10):
        authorize_goal(deep, steering_id=f"s{i}", task_id=f"goal{i}")
    assert remaining(deep, "searches") == 8
    assert remaining(deep, "wall_seconds") == 120
    assert remaining(deep, "python_runs") == 0


def test_no_uncalibrated_default_percentage_or_per_message_grant(monkeypatch):
    monkeypatch.delenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", raising=False)
    assert load_incremental_policy() is None
    deep = {}
    initialize_budget(deep, None)
    assert authorize_goal(deep, steering_id="s1", task_id="g1") == {}


@pytest.mark.parametrize("value", [-1, True, 0.5, float("inf")])
def test_invalid_policy_fails_closed(monkeypatch, value):
    invalid = copy.deepcopy(policy())
    invalid["per_goal"]["reads"] = value
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(invalid))
    with pytest.raises(ValueError):
        load_incremental_policy()
