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
import json
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
    dimensions = list((document.get("dimensions") or {}).keys())
    rows = []
    for task in document["tasks"]:
        applicable = [
            name
            for name in dimensions
            if name != "follow_up_correctness" or task.get("follow_up")
        ]
        for arm in arms:
            rows.append(
                {
                    "task_id": task["id"],
                    "task_type": task["type"],
                    "arm": arm,
                    "scores": {name: None for name in applicable},
                    "notes": "",
                    "diagnosis": "",
                    "first_useful_seconds": None,
                    "total_seconds": None,
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


def summarize(document: dict[str, Any], sheet: dict[str, Any]) -> dict[str, Any]:
    dimensions = document["dimensions"]
    rows = sheet.get("rows") or []
    expected = {
        (task["id"], arm["id"]) for task in document["tasks"] for arm in document["arms"]
    }
    seen = {(row["task_id"], row["arm"]) for row in rows}
    missing = expected - seen
    if missing:
        raise ValueError(f"sheet_missing_rows:{sorted(missing)[:5]}")
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
                weighted += (float(value) / float(spec["max"])) * float(spec["weight"])
                weight_sum += float(spec["weight"])
        summary["arms"][arm["id"]] = {
            "rows": len(arm_rows),
            "score_0_100": round(weighted / max(1.0, weight_sum) * 100, 1),
            "mean_first_useful_seconds": _mean(
                [row.get("first_useful_seconds") for row in arm_rows]
            ),
            "mean_total_seconds": _mean([row.get("total_seconds") for row in arm_rows]),
            "total_cost_cny": round(
                sum(float(row.get("cost_cny") or 0.0) for row in arm_rows), 3
            ),
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
