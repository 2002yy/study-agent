"""Offline contracts for Quality-0: the frozen task set and the scoring workflow.

These lock the properties the review asked for: complete dimension sets, unique
rows, bounded scores, fixed file assets, and unknown cost never counted as zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_quality_0 import (
    DEFAULT_TASKS,
    build_sheet,
    inventory,
    load_tasks,
    summarize,
)

REQUIRED_TYPES = {"chat", "game", "coding", "research", "science", "file", "interactive"}


@pytest.fixture
def document():
    return load_tasks(DEFAULT_TASKS)


def _complete_sheet(document, *, score: float = 4.0) -> dict:
    sheet = build_sheet(document)
    for row in sheet["rows"]:
        row["scores"] = {name: score for name in row["scores"]}
        row["first_useful_seconds"] = 2.0
        row["total_seconds"] = 10.0
        row["cost_status"] = "measured"
        row["cost_cny"] = 0.05
    return sheet


def test_task_set_covers_the_seven_product_areas(document):
    summary = inventory(document)

    assert summary["tasks"] == 20
    assert set(summary["by_type"]) == REQUIRED_TYPES
    assert sum(summary["by_type"].values()) == 20
    assert summary["multi_turn"] >= 5


def test_every_task_declares_expectation_failure_modes_and_dimensions(document):
    declared = set((document.get("dimensions") or {}).keys())
    for task in document["tasks"]:
        assert task["prompt"].strip()
        assert task["expected_behavior"].strip()
        assert task["checks"]
        assert task["must_not"]
        assert set(task["scoring_dimensions"]) <= declared


def test_freshness_only_applies_to_time_sensitive_tasks(document):
    for task in document["tasks"]:
        if "freshness" in task["scoring_dimensions"]:
            assert task["type"] == "game"


def test_follow_up_dimension_requires_a_second_turn(document):
    for task in document["tasks"]:
        if "follow_up_correctness" in task["scoring_dimensions"]:
            assert task.get("follow_up")


def test_file_tasks_carry_fixed_assets_with_content_hashes(document):
    file_tasks = [task for task in document["tasks"] if task["type"] == "file"]

    assert len(file_tasks) == 2
    for task in file_tasks:
        assert task["assets"]
        for asset in task["assets"]:
            path = Path(__file__).resolve().parents[1] / asset["path"]
            assert path.exists()
            assert len(asset["sha256"]) == 64


def test_a_wrong_asset_hash_is_rejected(document):
    broken = json.loads(json.dumps(document))
    file_task = next(task for task in broken["tasks"] if task["type"] == "file")
    file_task["assets"][0]["sha256"] = "0" * 64
    path = Path(__file__).parent / "_tmp_quality0_asset.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="asset_hash_mismatch"):
            load_tasks(path)
    finally:
        path.unlink(missing_ok=True)


def test_sheet_has_exactly_one_row_per_task_and_arm(document):
    sheet = build_sheet(document)

    assert len(sheet["rows"]) == 20 * len(document["arms"])
    keys = [(row["task_id"], row["arm"]) for row in sheet["rows"]]
    assert len(set(keys)) == len(keys)
    # Dimensions come from the task, not from a global list.
    single = next(row for row in sheet["rows"] if row["task_id"] == "GAME-01")
    assert "freshness" in single["scores"]
    assert "follow_up_correctness" not in single["scores"]
    multi = next(row for row in sheet["rows"] if row["task_id"] == "CHAT-01")
    assert "follow_up_correctness" in multi["scores"]
    assert "freshness" not in multi["scores"]


def test_summary_refuses_an_unscored_sheet(document):
    with pytest.raises(ValueError, match="sheet_unscored"):
        summarize(document, build_sheet(document))


def test_summary_refuses_duplicate_rows(document):
    sheet = _complete_sheet(document)
    sheet["rows"].append(dict(sheet["rows"][0]))

    with pytest.raises(ValueError, match="sheet_duplicate_rows"):
        summarize(document, sheet)


def test_summary_refuses_a_dropped_dimension(document):
    sheet = _complete_sheet(document)
    row = sheet["rows"][0]
    dropped = next(iter(row["scores"]))
    del row["scores"][dropped]

    with pytest.raises(ValueError, match="sheet_dimensions_mismatch"):
        summarize(document, sheet)


@pytest.mark.parametrize("bad", [40, -1, float("nan"), float("inf"), "4", True])
def test_out_of_range_or_non_numeric_scores_are_rejected(document, bad):
    sheet = _complete_sheet(document)
    row = sheet["rows"][0]
    name = next(iter(row["scores"]))
    row["scores"][name] = bad

    with pytest.raises(ValueError, match="sheet_score"):
        summarize(document, sheet)


def test_summary_scores_a_complete_sheet(document):
    summary = summarize(document, _complete_sheet(document))

    for arm in document["arms"]:
        result = summary["arms"][arm["id"]]
        assert result["score_0_100"] == 100.0
        assert result["mean_total_seconds"] == 10.0
        assert result["cost_complete"] is True
        assert result["total_cost_cny_measured"] == pytest.approx(0.05 * 20, abs=0.001)


def test_unknown_cost_is_not_counted_as_zero(document):
    sheet = _complete_sheet(document)
    row = sheet["rows"][0]
    row["cost_status"] = "not_measured"
    row["cost_cny"] = None

    summary = summarize(document, sheet)
    arm = summary["arms"][row["arm"]]

    assert arm["cost_not_measured_rows"] == 1
    assert arm["cost_measured_rows"] == 19
    assert arm["cost_complete"] is False
    assert arm["total_cost_cny_measured"] == pytest.approx(0.05 * 19, abs=0.001)


def test_a_cost_value_without_a_measured_status_is_rejected(document):
    sheet = _complete_sheet(document)
    sheet["rows"][0]["cost_status"] = "not_measured"

    with pytest.raises(ValueError, match="sheet_cost_inconsistent"):
        summarize(document, sheet)
