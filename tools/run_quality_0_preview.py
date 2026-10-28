"""Quality-0 preview: plan the four-task run and verify its budget guards.

Nothing here sends a request. The tool exists to make the paid run boring and
bounded before anyone authorises it:

- ``--plan`` (default) prints rounds, API rounds and the worst-case send count
  derived from the frozen preview fixture.
- ``--validate-budget`` additionally checks that a paid run *could* be enforced:
  explicit pricing, an existing ledger, admission already enabled, and limits that
  do not exceed the authorised 45 sends / 10 CNY.
- ``--live`` is refused on purpose: the arm execution is not wired in this slice,
  and a half-wired run (say, only the direct-model arm) would produce numbers
  nobody could compare.

The integument is deliberate: a plan that cannot pass these checks must not be
allowed to reach a provider later.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = REPO_ROOT / "tests" / "fixtures" / "quality_0" / "tasks_v1.json"
DEFAULT_PREVIEW = REPO_ROOT / "tests" / "fixtures" / "quality_0" / "preview_v1.json"

AUTHORISED_MAX_SENDS = 45
AUTHORISED_MAX_COST_CNY = 10.0
PRICE_KEYS = ("LLM_SPEND_INPUT_CNY_PER_MTOK", "LLM_SPEND_OUTPUT_CNY_PER_MTOK")
ADMISSION_FLAG = "STUDY_AGENT_SETTLEMENT_ADMISSION"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_preview(preview_path: Path, tasks_path: Path) -> dict[str, Any]:
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    by_id = {task["id"]: task for task in tasks["tasks"]}

    selected = preview.get("task_ids") or []
    if not selected:
        raise ValueError("preview_tasks_empty")
    unknown = [task_id for task_id in selected if task_id not in by_id]
    if unknown:
        raise ValueError(f"preview_unknown_tasks:{unknown}")

    arms = preview.get("arms") or []
    if not arms:
        raise ValueError("preview_arms_empty")
    for arm in arms:
        if arm.get("execution") not in {"api", "manual"}:
            raise ValueError(f"preview_arm_execution_invalid:{arm.get('id')}")
        sends = arm.get("sends_per_round")
        if not isinstance(sends, int) or isinstance(sends, bool) or sends < 0:
            raise ValueError(f"preview_arm_sends_invalid:{arm.get('id')}")
        if arm["execution"] == "manual" and sends != 0:
            raise ValueError(f"preview_manual_arm_must_not_send:{arm.get('id')}")

    preview["_tasks_by_id"] = by_id
    return preview


def plan(preview: dict[str, Any]) -> dict[str, Any]:
    by_id = preview["_tasks_by_id"]
    turns_per_arm = sum(
        1 + (1 if by_id[task_id].get("follow_up") else 0)
        for task_id in preview["task_ids"]
    )
    api_arms = [arm for arm in preview["arms"] if arm["execution"] == "api"]
    manual_arms = [arm for arm in preview["arms"] if arm["execution"] == "manual"]

    api_rounds = turns_per_arm * len(api_arms)
    user_rounds = turns_per_arm * len(preview["arms"])
    max_sends = turns_per_arm * sum(arm["sends_per_round"] for arm in api_arms)
    limits = preview.get("limits") or {}
    return {
        "tasks": preview["task_ids"],
        "turns_per_arm": turns_per_arm,
        "arms": [arm["id"] for arm in preview["arms"]],
        "api_arms": [arm["id"] for arm in api_arms],
        "manual_arms": [arm["id"] for arm in manual_arms],
        "api_rounds": api_rounds,
        "user_rounds": user_rounds,
        "worst_case_model_sends": max_sends,
        "declared_limits": limits,
        "within_authorised_sends": max_sends <= AUTHORISED_MAX_SENDS,
        "within_authorised_cost": float(limits.get("max_cost_cny") or 0)
        <= AUTHORISED_MAX_COST_CNY,
    }


def validate_budget(preview: dict[str, Any], plan_doc: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []

    limits = preview.get("limits") or {}
    declared_sends = limits.get("max_model_sends")
    declared_cost = limits.get("max_cost_cny")
    if not isinstance(declared_sends, int) or declared_sends > AUTHORISED_MAX_SENDS:
        problems.append("limit_sends_exceeds_authorisation")
    if plan_doc["worst_case_model_sends"] > AUTHORISED_MAX_SENDS:
        problems.append("plan_sends_exceed_authorisation")
    if not isinstance(declared_cost, (int, float)) or declared_cost > AUTHORISED_MAX_COST_CNY:
        problems.append("limit_cost_exceeds_authorisation")
    if plan_doc["worst_case_model_sends"] > int(declared_sends or 0):
        problems.append("plan_sends_exceed_declared_limit")

    for key in PRICE_KEYS:
        raw = (os.environ.get(key) or "").strip()
        try:
            value = float(raw)
        except ValueError:
            problems.append(f"pricing_missing_or_invalid:{key}")
            continue
        if not math.isfinite(value) or value <= 0:
            problems.append(f"pricing_missing_or_invalid:{key}")

    if (os.environ.get(ADMISSION_FLAG) or "").strip().lower() not in {"1", "true", "on", "yes"}:
        problems.append("admission_not_enabled")

    if not (os.environ.get("LLM_SPEND_LEDGER_DB") or "").strip():
        problems.append("ledger_not_configured")

    if not (os.environ.get("LLM_SPEND_EXPERIMENT_ID") or "").strip():
        problems.append("experiment_not_configured")

    return {
        "ok": not problems,
        "problems": problems,
        "checked_at": _utc_now(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument(
        "--validate-budget",
        action="store_true",
        help="check pricing, ledger, admission and limits; still sends nothing",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="refused in this slice: arm execution is not wired yet",
    )
    args = parser.parse_args(argv)

    preview = load_preview(args.preview.resolve(), args.tasks.resolve())
    plan_doc = plan(preview)

    if args.live:
        print(
            "refusing --live: arm execution is not wired in this slice; "
            "use --plan or --validate-budget"
        )
        return 2

    if args.validate_budget:
        result = validate_budget(preview, plan_doc)
        print(json.dumps({**plan_doc, "budget_check": result}, ensure_ascii=False, sort_keys=True))
        return 0 if result["ok"] else 1

    print(json.dumps(plan_doc, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] if len(sys.argv) > 1 else None))
