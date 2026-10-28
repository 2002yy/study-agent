"""Offline contracts for Quality-0: the frozen task set and the scoring workflow."""

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


def test_task_set_covers_the_seven_product_areas(document):
    summary = inventory(document)

    assert summary["tasks"] == 20
    assert set(summary["by_type"]) == REQUIRED_TYPES
    assert sum(summary["by_type"].values()) == 20
    assert summary["multi_turn"] >= 5


def test_every_task_declares_expectation_and_failure_modes(document):
    for task in document["tasks"]:
        assert task["prompt"].strip()
        assert task["expected_behavior"].strip()
        assert task["checks"]
        assert task["must_not"]


def test_sheet_has_a_row_for_every_task_and_arm(document):
    sheet = build_sheet(document)

    assert len(sheet["rows"]) == 20 * len(document["arms"])
    keys = {(row["task_id"], row["arm"]) for row in sheet["rows"]}
    assert len(keys) == len(sheet["rows"])
    # follow_up_correctness only applies where there is a second turn.
    follow_rows = [row for row in sheet["rows"] if row["task_id"] == "CHAT-01"]
    assert "follow_up_correctness" in follow_rows[0]["scores"]
    single = [row for row in sheet["rows"] if row["task_id"] == "GAME-01"]
    assert "follow_up_correctness" not in single[0]["scores"]


def test_summary_refuses_an_unscored_sheet(document):
    sheet = build_sheet(document)

    with pytest.raises(ValueError, match="sheet_unscored"):
        summarize(document, sheet)


def test_summary_refuses_a_sheet_missing_rows(document):
    sheet = build_sheet(document)
    sheet["rows"] = sheet["rows"][:-1]

    with pytest.raises(ValueError, match="sheet_missing_rows"):
        summarize(document, sheet)


def test_summary_scores_a_complete_sheet(document):
    sheet = build_sheet(document)
    for row in sheet["rows"]:
        row["scores"] = {name: 4 for name in row["scores"]}
        row["first_useful_seconds"] = 2.0
        row["total_seconds"] = 10.0
        row["cost_cny"] = 0.05

    summary = summarize(document, sheet)

    for arm in document["arms"]:
        result = summary["arms"][arm["id"]]
        assert result["score_0_100"] == 100.0
        assert result["mean_total_seconds"] == 10.0
        assert result["total_cost_cny"] == pytest.approx(0.05 * 20, abs=0.001)


def test_invalid_sheets_are_rejected_before_scoring(document):
    broken = json.loads(json.dumps(document))
    broken["tasks"][0]["id"] = broken["tasks"][1]["id"]
    path = Path(__file__).parent / "_tmp_quality0_doc.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="duplicate_task_id"):
            load_tasks(path)
    finally:
        path.unlink(missing_ok=True)
