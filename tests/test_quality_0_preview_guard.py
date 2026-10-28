"""Offline contracts for the Quality-0 preview plan and its budget guards.

Two properties are locked here, because both were review findings:

* identity is frozen - the four tasks, the four arms, their execution type and
  their per-round send cap cannot be swapped, duplicated or relaxed;
* numbers fail closed - a NaN, infinite, negative, zero, boolean or string limit
  is reported as an invalid configuration, never coerced into something that
  passes. The effective spend-guard cap must exist and stay inside the
  authorised envelope, otherwise a "validated" budget would not be enforced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_quality_0_preview as preview_mod
from tools.run_quality_0_preview import (
    AUTHORISED_MAX_SENDS,
    load_preview,
    main,
    plan,
    validate_budget,
)

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "tests" / "fixtures" / "quality_0" / "tasks_v1.json"
PREVIEW = ROOT / "tests" / "fixtures" / "quality_0" / "preview_v1.json"


@pytest.fixture
def preview():
    return load_preview(PREVIEW, TASKS)


def _raw() -> dict:
    return json.loads(PREVIEW.read_text(encoding="utf-8"))


def _write(tmp_path, document) -> Path:
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _ready_env(monkeypatch, tmp_path, *, cap: str | None = "8") -> None:
    monkeypatch.setenv(preview_mod.PRICE_KEYS[0], "4")
    monkeypatch.setenv(preview_mod.PRICE_KEYS[1], "16")
    monkeypatch.setenv(preview_mod.ADMISSION_FLAG, "1")
    # A real absolute path on every platform; "C:/ledger.db" is relative on Linux
    # and would be refused as ledger_not_absolute.
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "q0-preview")
    monkeypatch.delenv("LLM_SPEND_CAP_CNY", raising=False)
    monkeypatch.delenv("LLM_SPEND_EXPERIMENT_CAP_CNY", raising=False)
    if cap is not None:
        monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)


def _clear_budget_env(monkeypatch):
    for key in (
        *preview_mod.PRICE_KEYS,
        preview_mod.ADMISSION_FLAG,
        "LLM_SPEND_LEDGER_DB",
        "LLM_SPEND_EXPERIMENT_ID",
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_EXPERIMENT_CAP_CNY",
    ):
        monkeypatch.delenv(key, raising=False)


# --- identity -------------------------------------------------------------


def test_plan_matches_the_authorised_shape(preview):
    doc = plan(preview)

    assert doc["tasks"] == ["CHAT-01", "GAME-02", "CODE-01", "FILE-02"]
    assert doc["turns_per_arm"] == 5
    assert doc["api_rounds"] == 15
    assert doc["user_rounds"] == 20
    assert doc["worst_case_model_sends"] == AUTHORISED_MAX_SENDS
    assert doc["per_arm"]["current"]["max_sends"] == 20
    assert doc["per_arm"]["model_direct"]["max_sends"] == 5
    assert doc["per_arm"]["chatgpt"]["max_sends"] == 0
    assert doc["within_authorised_sends"] is True
    assert doc["within_authorised_cost"] is True


def test_task_order_is_irrelevant_but_the_set_is_not(tmp_path):
    reordered = _raw()
    reordered["task_ids"] = list(reversed(reordered["task_ids"]))

    loaded = load_preview(_write(tmp_path, reordered), TASKS)

    assert set(loaded["task_ids"]) == set(reordered["task_ids"])


def test_swapping_a_task_is_refused(tmp_path):
    swapped = _raw()
    swapped["task_ids"] = ["CHAT-01", "GAME-02", "CODE-01", "FILE-01"]

    with pytest.raises(ValueError, match="preview_tasks_mismatch"):
        load_preview(_write(tmp_path, swapped), TASKS)


def test_dropping_or_duplicating_a_task_is_refused(tmp_path):
    dropped = _raw()
    dropped["task_ids"] = dropped["task_ids"][:-1]
    with pytest.raises(ValueError, match="preview_tasks_mismatch"):
        load_preview(_write(tmp_path, dropped), TASKS)

    duplicated = _raw()
    duplicated["task_ids"] = [*duplicated["task_ids"], "CODE-01"]
    with pytest.raises(ValueError, match="preview_tasks_duplicate"):
        load_preview(_write(tmp_path, duplicated), TASKS)


def test_an_unknown_task_is_refused(tmp_path):
    broken = _raw()
    broken["task_ids"] = [*broken["task_ids"][:-1], "NOPE-01"]

    with pytest.raises(ValueError, match="preview_tasks_mismatch"):
        load_preview(_write(tmp_path, broken), TASKS)


def test_a_manual_arm_must_not_send(tmp_path):
    broken = _raw()
    broken["arms"][-1]["sends_per_round"] = 1

    with pytest.raises(ValueError, match="preview_arm_shape_mismatch:chatgpt"):
        load_preview(_write(tmp_path, broken), TASKS)


def test_relabelling_an_arm_as_manual_is_refused(tmp_path):
    broken = _raw()
    broken["arms"][0]["execution"] = "manual"

    with pytest.raises(ValueError, match="preview_arm_shape_mismatch:current"):
        load_preview(_write(tmp_path, broken), TASKS)


def test_dropping_or_duplicating_an_arm_is_refused(tmp_path):
    dropped = _raw()
    dropped["arms"] = dropped["arms"][:-1]
    with pytest.raises(ValueError, match="preview_arms_mismatch"):
        load_preview(_write(tmp_path, dropped), TASKS)

    duplicated = _raw()
    duplicated["arms"] = [*duplicated["arms"], dict(duplicated["arms"][0])]
    with pytest.raises(ValueError, match="preview_arms_duplicate"):
        load_preview(_write(tmp_path, duplicated), TASKS)


def test_missing_limits_are_refused(tmp_path):
    broken = _raw()
    del broken["limits"]["max_api_rounds"]

    with pytest.raises(ValueError, match="preview_limits_missing"):
        load_preview(_write(tmp_path, broken), TASKS)


# --- numbers --------------------------------------------------------------


# Raw JSON tokens: a hand-edited fixture can carry NaN/Infinity, which json
# accepts even though strict JSON does not.
@pytest.mark.parametrize(
    "bad",
    ["NaN", "Infinity", "-Infinity", "-1", "0", "true", '"10"'],
)
def test_invalid_cost_limits_fail_closed(monkeypatch, tmp_path, bad):
    _ready_env(monkeypatch, tmp_path)
    text = json.dumps(_raw()).replace('"max_cost_cny": 10', f'"max_cost_cny": {bad}')
    path = tmp_path / "preview.json"
    path.write_text(text, encoding="utf-8")

    loaded = load_preview(path, TASKS)
    result = validate_budget(loaded, plan(loaded))

    assert result["ok"] is False
    assert any(problem.startswith("limit_cost_invalid") for problem in result["problems"])


@pytest.mark.parametrize("bad", ["NaN", "-1", "0", "true", '"45"', "1.5"])
def test_invalid_send_limits_fail_closed(monkeypatch, tmp_path, bad):
    _ready_env(monkeypatch, tmp_path)
    text = json.dumps(_raw()).replace('"max_model_sends": 45', f'"max_model_sends": {bad}')
    path = tmp_path / "preview.json"
    path.write_text(text, encoding="utf-8")

    loaded = load_preview(path, TASKS)
    result = validate_budget(loaded, plan(loaded))

    assert result["ok"] is False
    assert any(
        problem.startswith("limit_not_integer")
        or problem.startswith("limit_not_positive")
        for problem in result["problems"]
    )


@pytest.mark.parametrize("key", ["max_user_rounds", "max_api_rounds"])
def test_round_limits_are_enforced_not_just_declared(preview, monkeypatch, tmp_path, key):
    _ready_env(monkeypatch, tmp_path)
    broken = _raw()
    broken["limits"][key] = 0

    loaded = load_preview(_write(tmp_path, broken), TASKS)
    result = validate_budget(loaded, plan(loaded))

    assert result["ok"] is False
    assert any(
        problem.startswith(f"limit_not_positive:{key}") for problem in result["problems"]
    )


def test_a_declared_send_cap_over_the_authorisation_is_refused(monkeypatch, tmp_path):
    _ready_env(monkeypatch, tmp_path)
    over = _raw()
    over["limits"]["max_model_sends"] = 50
    loaded = load_preview(_write(tmp_path, over), TASKS)

    result = validate_budget(loaded, plan(loaded))

    assert result["ok"] is False
    assert any(
        problem.startswith("limit_exceeds_authorisation:max_model_sends")
        for problem in result["problems"]
    )
    assert "plan_sends_exceed_declared_limit" not in result["problems"]


def test_budget_check_fails_closed_without_pricing(preview, monkeypatch, tmp_path):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv(preview_mod.ADMISSION_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "q0-preview")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "8")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert any(
        problem.startswith("pricing_missing_or_invalid") for problem in result["problems"]
    )


def test_budget_check_fails_closed_without_admission(preview, monkeypatch, tmp_path):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv(preview_mod.PRICE_KEYS[0], "4")
    monkeypatch.setenv(preview_mod.PRICE_KEYS[1], "16")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "q0-preview")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "8")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert "admission_not_enabled" in result["problems"]


def test_budget_check_needs_an_effective_cap(preview, monkeypatch, tmp_path):
    _ready_env(monkeypatch, tmp_path, cap=None)

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    # Without a cap the guard's reserve_call() returns 0.0 and spends freely.
    assert "experiment_cap_missing" in result["problems"]


def test_a_guard_cap_over_the_authorisation_is_refused(preview, monkeypatch, tmp_path):
    _ready_env(monkeypatch, tmp_path, cap="20")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert any(
        problem.startswith("experiment_cap_exceeds_authorisation")
        for problem in result["problems"]
    )


def test_a_non_finite_guard_cap_is_refused(preview, monkeypatch, tmp_path):
    _ready_env(monkeypatch, tmp_path, cap="NaN")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert any(
        problem.startswith("experiment_cap_invalid") for problem in result["problems"]
    )


def test_a_relative_ledger_path_is_refused(preview, monkeypatch, tmp_path):
    _ready_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", "ledger.db")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert "ledger_not_absolute" in result["problems"]


def test_budget_check_passes_when_every_condition_holds(preview, monkeypatch, tmp_path):
    _ready_env(monkeypatch, tmp_path, cap="8")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is True
    assert result["problems"] == []
    assert result["effective_cap_cny"] == 8.0


# --- CLI ------------------------------------------------------------------


def test_plan_option_is_registered(capsys):
    assert main(["--plan"]) == 0
    assert '"worst_case_model_sends": 45' in capsys.readouterr().out


def test_live_is_refused_in_this_slice(capsys):
    assert main(["--live"]) == 2
    assert "refusing --live" in capsys.readouterr().out
