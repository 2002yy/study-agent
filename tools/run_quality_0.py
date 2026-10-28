"""Quality-0: a frozen real-task set and an offline scoring workflow.

This tool never calls a model and never runs a chat. It exists so the product
comparison is defined before any paid run:

- ``--validate`` (default) checks the frozen task set and prints its inventory.
- ``--sheet`` writes an empty scoring sheet (task x arm x dimension) that a human
  or an independent judge fills in later.
- ``--summarize`` refuses an incomplete sheet, then reports weighted scores.

A paid run needs its own authorisation and a separate harness; nothing here can
start one by accident.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = REPO_ROOT / "tests" / "fixtures" / "quality_0" / "tasks_v1.json"
DEFAULT_SHEET = REPO_ROOT / "docs" / "research_quality" / "QUALITY_0_SCORING_SHEET.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_tasks(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks_empty")

    ids: set[str] = set()
    for task in tasks:
        missing = {
            "id",
            "type",
            "prompt",
            "expected_behavior",
            "checks",
            "must_not",
            "scoring_dimensions",
        } - set(task or {})
        if missing:
            raise ValueError(f"task_missing_fields:{sorted(missing)}")
        if task["id"] in ids:
            raise ValueError(f"duplicate_task_id:{task['id']}")
        ids.add(task["id"])

    dimensions = document.get("dimensions") or {}
    if not dimensions:
        raise ValueError("dimensions_empty")
    total_weight = sum(float(item.get("weight") or 0) for item in dimensions.values())
    if total_weight <= 0:
        raise ValueError("dimension_weights_invalid")

    for task in tasks:
        applied = list(task["scoring_dimensions"])
        unknown = set(applied) - set(dimensions)
        if unknown or not applied:
            raise ValueError(f"task_dimensions_invalid:{task['id']}:{sorted(unknown)}")
        # A dimension that does not apply must not be silently droppable: the
        # sheet is validated against this exact list, so an evaluator cannot
        # remove an inconvenient dimension and raise the score.
        if "follow_up_correctness" in applied and not task.get("follow_up"):
            raise ValueError(f"follow_up_dimension_without_follow_up:{task['id']}")
        if "freshness" in applied and task["type"] != "game":
            raise ValueError(f"freshness_dimension_not_applicable:{task['id']}")
        for asset in task.get("assets", []):
            asset_path = REPO_ROOT / asset["path"]
            if not asset_path.exists():
                raise ValueError(f"asset_missing:{asset['path']}")
            digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
            if digest != asset["sha256"]:
                raise ValueError(f"asset_hash_mismatch:{asset['path']}")

    arms = document.get("arms") or []
    if not arms:
        raise ValueError("arms_empty")
    return document


def inventory(document: dict[str, Any]) -> dict[str, Any]:
    tasks = document["tasks"]
    by_type: dict[str, int] = {}
    for task in tasks:
        by_type[task["type"]] = by_type.get(task["type"], 0) + 1
    return {
        "schema_version": document.get("schema_version"),
        "frozen_at": document.get("frozen_at"),
        "tasks": len(tasks),
        "by_type": by_type,
        "multi_turn": sum(1 for task in tasks if task.get("follow_up")),
        "arms": [arm["id"] for arm in document.get("arms", [])],
        "dimensions": list((document.get("dimensions") or {}).keys()),
    }


def build_sheet(document: dict[str, Any]) -> dict[str, Any]:
    arms = [arm["id"] for arm in document["arms"]]
    rows = []
    for task in document["tasks"]:
        applicable = list(task["scoring_dimensions"])
        for arm in arms:
            rows.append(
                {
                    "task_id": task["id"],
                    "task_type": task["type"],
                    "dimensions": applicable,
                    "arm": arm,
                    "scores": {name: None for name in applicable},
                    "notes": "",
                    "diagnosis": "",
                    "first_useful_seconds": None,
                    "total_seconds": None,
                    "cost_status": "not_measured",
                    "cost_cny": None,
                }
            )
    return {
        "schema_version": "quality-0-scoring-sheet-v1",
        "created_at": _utc_now(),
        "tasks_fixture_version": document.get("schema_version"),
        "tasks_fixture_frozen_at": document.get("frozen_at"),
        "dimensions": document.get("dimensions"),
        "rows": rows,
    }


def _checked_score(task_id: str, name: str, value: Any, spec: dict[str, Any]) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"sheet_score_invalid:{task_id}:{name}:{value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0 or number > float(spec["max"]):
        raise ValueError(f"sheet_score_out_of_range:{task_id}:{name}:{value!r}")
    return number


def summarize(document: dict[str, Any], sheet: dict[str, Any]) -> dict[str, Any]:
    dimensions = document["dimensions"]
    rows = sheet.get("rows") or []
    expected = {
        (task["id"], arm["id"]) for task in document["tasks"] for arm in document["arms"]
    }
    seen = [(row["task_id"], row["arm"]) for row in rows]
    if len(set(seen)) != len(seen):
        raise ValueError("sheet_duplicate_rows")
    missing = expected - set(seen)
    if missing:
        raise ValueError(f"sheet_missing_rows:{sorted(missing)[:5]}")
    unexpected = set(seen) - expected
    if unexpected:
        raise ValueError(f"sheet_unexpected_rows:{sorted(unexpected)[:5]}")

    task_by_id = {task["id"]: task for task in document["tasks"]}
    for row in rows:
        applied = task_by_id[row["task_id"]]["scoring_dimensions"]
        if set(row.get("scores") or {}) != set(applied):
            raise ValueError(f"sheet_dimensions_mismatch:{row['task_id']}/{row['arm']}")

    unscored = [
        f"{row['task_id']}/{row['arm']}:{name}"
        for row in rows
        for name, value in (row.get("scores") or {}).items()
        if value is None
    ]
    if unscored:
        raise ValueError(f"sheet_unscored:{unscored[:5]}")

    summary: dict[str, Any] = {"rows": len(rows), "arms": {}}
    for arm in document["arms"]:
        arm_rows = [row for row in rows if row["arm"] == arm["id"]]
        weighted = 0.0
        weight_sum = 0.0
        for row in arm_rows:
            for name, value in row["scores"].items():
                spec = dimensions[name]
                weighted += (
                    _checked_score(row["task_id"], name, value, spec)
                    / float(spec["max"])
                ) * float(spec["weight"])
                weight_sum += float(spec["weight"])

        measured_costs: list[float] = []
        not_measured = 0
        for row in arm_rows:
            status = row.get("cost_status")
            if status == "measured":
                value = row.get("cost_cny")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"sheet_cost_invalid:{row['task_id']}/{row['arm']}")
                if not math.isfinite(float(value)) or float(value) < 0:
                    raise ValueError(f"sheet_cost_invalid:{row['task_id']}/{row['arm']}")
                measured_costs.append(float(value))
            elif status == "not_measured":
                if row.get("cost_cny") is not None:
                    raise ValueError(
                        f"sheet_cost_inconsistent:{row['task_id']}/{row['arm']}"
                    )
                not_measured += 1
            else:
                raise ValueError(
                    f"sheet_cost_status_invalid:{row['task_id']}/{row['arm']}:{status!r}"
                )

        summary["arms"][arm["id"]] = {
            "rows": len(arm_rows),
            "score_0_100": round(weighted / max(1.0, weight_sum) * 100, 1),
            "mean_first_useful_seconds": _mean(
                [row.get("first_useful_seconds") for row in arm_rows]
            ),
            "mean_total_seconds": _mean([row.get("total_seconds") for row in arm_rows]),
            "cost_measured_rows": len(measured_costs),
            "cost_not_measured_rows": not_measured,
            "total_cost_cny_measured": round(sum(measured_costs), 3),
            "cost_complete": not_measured == 0,
        }
    return summary


def _mean(values: list[Any]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    parser.add_argument(
        "--write-sheet",
        action="store_true",
        help="write an empty scoring sheet (offline; nothing is executed)",
    )
    parser.add_argument(
        "--summarize",
        type=Path,
        default=None,
        help="summarise a completed scoring sheet; incomplete sheets are refused",
    )
    args = parser.parse_args()

    document = load_tasks(args.tasks.resolve())

    if args.summarize is not None:
        sheet = json.loads(args.summarize.read_text(encoding="utf-8"))
        print(json.dumps(summarize(document, sheet), ensure_ascii=False, sort_keys=True))
        return 0

    if args.write_sheet:
        sheet = build_sheet(document)
        args.sheet.parent.mkdir(parents=True, exist_ok=True)
        args.sheet.write_text(
            json.dumps(sheet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.sheet} ({len(sheet['rows'])} rows)")
        return 0

    print(json.dumps(inventory(document), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
