"""Offline contracts for the Quality-0 preview plan and its budget guards."""

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


def test_plan_matches_the_authorised_shape(preview):
    doc = plan(preview)

    assert doc["tasks"] == ["CHAT-01", "GAME-02", "CODE-01", "FILE-02"]
    assert doc["turns_per_arm"] == 5
    assert doc["api_rounds"] == 15
    assert doc["user_rounds"] == 20
    assert doc["worst_case_model_sends"] == AUTHORISED_MAX_SENDS
    assert doc["within_authorised_sends"] is True
    assert doc["within_authorised_cost"] is True


def test_plan_rejects_an_unknown_task(tmp_path, preview):
    broken = json.loads(PREVIEW.read_text(encoding="utf-8"))
    broken["task_ids"] = [*broken["task_ids"], "NOPE-01"]
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="preview_unknown_tasks"):
        load_preview(path, TASKS)


def test_a_manual_arm_must_not_send(tmp_path):
    broken = json.loads(PREVIEW.read_text(encoding="utf-8"))
    broken["arms"][-1]["sends_per_round"] = 1
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="preview_manual_arm_must_not_send"):
        load_preview(path, TASKS)


def _clear_budget_env(monkeypatch):
    for key in (
        *preview_mod.PRICE_KEYS,
        preview_mod.ADMISSION_FLAG,
        "LLM_SPEND_LEDGER_DB",
        "LLM_SPEND_EXPERIMENT_ID",
    ):
        monkeypatch.delenv(key, raising=False)


def test_budget_check_fails_closed_without_pricing(preview, monkeypatch):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv(preview_mod.ADMISSION_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", "C:/ledger.db")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "q0-preview")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert any(problem.startswith("pricing_missing_or_invalid") for problem in result["problems"])


def test_budget_check_fails_closed_without_admission(preview, monkeypatch):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv(preview_mod.PRICE_KEYS[0], "4")
    monkeypatch.setenv(preview_mod.PRICE_KEYS[1], "16")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", "C:/ledger.db")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "q0-preview")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is False
    assert "admission_not_enabled" in result["problems"]


def test_budget_check_passes_when_every_condition_holds(preview, monkeypatch):
    _clear_budget_env(monkeypatch)
    monkeypatch.setenv(preview_mod.PRICE_KEYS[0], "4")
    monkeypatch.setenv(preview_mod.PRICE_KEYS[1], "16")
    monkeypatch.setenv(preview_mod.ADMISSION_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", "C:/ledger.db")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "q0-preview")

    result = validate_budget(preview, plan(preview))

    assert result["ok"] is True
    assert result["problems"] == []


def test_a_plan_over_the_send_cap_is_refused(tmp_path):
    over = json.loads(PREVIEW.read_text(encoding="utf-8"))
    over["arms"][0]["sends_per_round"] = 5  # 5*5 + 4*5 + 1*5 = 50 sends
    over["limits"]["max_model_sends"] = 50
    path = tmp_path / "preview.json"
    path.write_text(json.dumps(over), encoding="utf-8")
    loaded = load_preview(path, TASKS)

    result = validate_budget(loaded, plan(loaded))

    assert result["ok"] is False
    assert "plan_sends_exceed_authorisation" in result["problems"]
    assert "plan_sends_exceed_declared_limit" not in result["problems"]


def test_live_is_refused_in_this_slice(capsys):
    assert main(["--live"]) == 2
    assert "refusing --live" in capsys.readouterr().out
