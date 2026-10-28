"""Quality-0 preview: plan the four-task run and verify its budget guards.

Nothing here sends a request. The tool exists to make the paid run boring and
bounded before anyone authorises it:

- ``--plan`` (default) prints rounds, API rounds and the worst-case send count
  derived from the frozen preview fixture.
- ``--validate-budget`` additionally checks that a paid run *could* be enforced:
  explicit pricing, an effective spend cap, an existing ledger, admission already
  enabled, and limits that do not exceed the authorised 45 sends / 10 CNY.
- ``--live`` is refused on purpose: the arm execution is not wired in this slice,
  and a half-wired run (say, only the direct-model arm) would produce numbers
  nobody could compare.

The two contracts are deliberately separate. ``load_preview`` freezes *identity*:
which four tasks, which four arms, which execution type and per-round send count.
``validate_budget`` freezes *numbers*: every limit must be a finite, positive
value inside the authorised envelope, and invalid input is reported as
``ok=false`` rather than being coerced into something that looks safe.
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

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The authorised preview, as frozen by the owner. A preview that renames a task,
# drops an arm or relaxes a per-round cap is a different experiment, and must be
# rejected rather than silently re-planned.
FROZEN_TASK_IDS = ("CHAT-01", "GAME-02", "CODE-01", "FILE-02")
FROZEN_ARMS = (
    # (id, execution, sends_per_round)
    ("current", "api", 4),
    ("candidate", "api", 4),
    ("model_direct", "api", 1),
    ("chatgpt", "manual", 0),
)
AUTHORISED_MAX_USER_ROUNDS = 20
AUTHORISED_MAX_API_ROUNDS = 15
AUTHORISED_MAX_SENDS = 45
AUTHORISED_MAX_COST_CNY = 10.0

PRICE_KEYS = ("LLM_SPEND_INPUT_CNY_PER_MTOK", "LLM_SPEND_OUTPUT_CNY_PER_MTOK")
ADMISSION_FLAG = "STUDY_AGENT_SETTLEMENT_ADMISSION"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"preview_{label}_unreadable") from exc


def _check_task_ids(preview: dict[str, Any], by_id: dict[str, Any]) -> None:
    selected = preview.get("task_ids")
    if not isinstance(selected, list) or not selected:
        raise ValueError("preview_tasks_empty")
    if any(not isinstance(task_id, str) for task_id in selected):
        raise ValueError("preview_tasks_invalid")
    if len(set(selected)) != len(selected):
        raise ValueError("preview_tasks_duplicate")
    # Order is presentation only; the *set* is the experiment.
    if set(selected) != set(FROZEN_TASK_IDS):
        raise ValueError(
            "preview_tasks_mismatch:"
            f"expected={sorted(FROZEN_TASK_IDS)}:actual={sorted(selected)}"
        )
    unknown = [task_id for task_id in selected if task_id not in by_id]
    if unknown:
        raise ValueError(f"preview_unknown_tasks:{unknown}")


def _check_arms(preview: dict[str, Any]) -> None:
    arms = preview.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ValueError("preview_arms_empty")
    ids = [arm.get("id") if isinstance(arm, dict) else None for arm in arms]
    if any(not isinstance(arm_id, str) for arm_id in ids):
        raise ValueError("preview_arms_invalid")
    if len(set(ids)) != len(ids):
        raise ValueError("preview_arms_duplicate")
    if set(ids) != {arm_id for arm_id, _, _ in FROZEN_ARMS}:
        raise ValueError(f"preview_arms_mismatch:actual={sorted(ids)}")

    frozen = {arm_id: (execution, sends) for arm_id, execution, sends in FROZEN_ARMS}
    for arm in arms:
        execution, sends = frozen[arm["id"]]
        if arm.get("execution") != execution or arm.get("sends_per_round") != sends:
            raise ValueError(f"preview_arm_shape_mismatch:{arm['id']}")


def _check_limits(preview: dict[str, Any]) -> None:
    limits = preview.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("preview_limits_invalid")
    required = ("max_user_rounds", "max_api_rounds", "max_model_sends", "max_cost_cny")
    missing = [key for key in required if key not in limits]
    if missing:
        raise ValueError(f"preview_limits_missing:{missing}")


def load_preview(preview_path: Path, tasks_path: Path) -> dict[str, Any]:
    preview = _read_json(preview_path, "config")
    if not isinstance(preview, dict):
        raise ValueError("preview_config_invalid")
    tasks = _read_json(tasks_path, "tasks")
    if not isinstance(tasks, dict) or not isinstance(tasks.get("tasks"), list):
        raise ValueError("preview_tasks_fixture_invalid")
    by_id = {task["id"]: task for task in tasks["tasks"]}

    _check_task_ids(preview, by_id)
    _check_arms(preview)
    _check_limits(preview)

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

    per_arm = {
        arm["id"]: {
            "execution": arm["execution"],
            "sends_per_round": arm["sends_per_round"],
            # Per-round caps are the point: a round may never borrow from another
            # round's unused budget, so this product is the whole allowance.
            "max_sends": arm["sends_per_round"] * turns_per_arm,
        }
        for arm in preview["arms"]
    }
    api_rounds = turns_per_arm * len(api_arms)
    user_rounds = turns_per_arm * len(preview["arms"])
    max_sends = sum(item["max_sends"] for item in per_arm.values())
    limits = preview.get("limits") or {}
    return {
        "tasks": list(preview["task_ids"]),
        "turns_per_arm": turns_per_arm,
        "arms": [arm["id"] for arm in preview["arms"]],
        "api_arms": [arm["id"] for arm in api_arms],
        "manual_arms": [arm["id"] for arm in manual_arms],
        "per_arm": per_arm,
        "api_rounds": api_rounds,
        "user_rounds": user_rounds,
        "worst_case_model_sends": max_sends,
        "declared_limits": limits,
        "within_authorised_sends": max_sends <= AUTHORISED_MAX_SENDS,
        "within_authorised_cost": _is_safe_cost(limits.get("max_cost_cny")),
    }


def _is_safe_cost(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and 0 < number <= AUTHORISED_MAX_COST_CNY


def _strict_limit(
    problems: list[str], limits: dict[str, Any], key: str, authorised: int
) -> int | None:
    """Validate an integer limit; report instead of guessing when it is invalid."""

    value = limits.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        problems.append(f"limit_not_integer:{key}:{value!r}")
        return None
    if value <= 0:
        problems.append(f"limit_not_positive:{key}:{value!r}")
        return None
    if value > authorised:
        problems.append(f"limit_exceeds_authorisation:{key}:{value}>{authorised}")
        return value
    return value


def _effective_cap(problems: list[str]) -> float | None:
    """The cap the spend guard will actually enforce, or None when it has one."""

    try:
        from src.llm_spend_guard import experiment_cap_cny
    except Exception:  # pragma: no cover - import failure means no guard at all
        problems.append("spend_guard_unavailable")
        return None
    try:
        cap = experiment_cap_cny()
    except Exception as exc:
        problems.append(f"experiment_cap_invalid:{exc}")
        return None
    if cap is None:
        problems.append("experiment_cap_missing")
        return None
    if not math.isfinite(cap) or cap <= 0:
        problems.append(f"experiment_cap_invalid:{cap}")
        return None
    if cap > AUTHORISED_MAX_COST_CNY:
        problems.append(
            f"experiment_cap_exceeds_authorisation:{cap}>{AUTHORISED_MAX_COST_CNY}"
        )
    return cap


def validate_budget(preview: dict[str, Any], plan_doc: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    limits = preview.get("limits") or {}

    declared_sends = _strict_limit(
        problems, limits, "max_model_sends", AUTHORISED_MAX_SENDS
    )
    declared_rounds = _strict_limit(
        problems, limits, "max_user_rounds", AUTHORISED_MAX_USER_ROUNDS
    )
    declared_api_rounds = _strict_limit(
        problems, limits, "max_api_rounds", AUTHORISED_MAX_API_ROUNDS
    )

    # NaN compares False against every bound, so ``value > cap`` alone would let
    # it through. Costs are therefore checked for type, finiteness and positivity
    # before any comparison.
    declared_cost = limits.get("max_cost_cny")
    cost_number: float | None = None
    if isinstance(declared_cost, bool) or not isinstance(declared_cost, (int, float)):
        problems.append(f"limit_cost_invalid:{declared_cost!r}")
    else:
        cost_number = float(declared_cost)
        if not math.isfinite(cost_number) or cost_number <= 0:
            problems.append(f"limit_cost_invalid:{declared_cost!r}")
            cost_number = None
        elif cost_number > AUTHORISED_MAX_COST_CNY:
            problems.append(
                f"limit_cost_exceeds_authorisation:{cost_number}>{AUTHORISED_MAX_COST_CNY}"
            )

    if plan_doc["worst_case_model_sends"] > AUTHORISED_MAX_SENDS:
        problems.append("plan_sends_exceed_authorisation")
    if plan_doc["user_rounds"] > AUTHORISED_MAX_USER_ROUNDS:
        problems.append("plan_user_rounds_exceed_authorisation")
    if plan_doc["api_rounds"] > AUTHORISED_MAX_API_ROUNDS:
        problems.append("plan_api_rounds_exceed_authorisation")

    if declared_sends is not None and plan_doc["worst_case_model_sends"] > declared_sends:
        problems.append("plan_sends_exceed_declared_limit")
    if declared_rounds is not None and plan_doc["user_rounds"] > declared_rounds:
        problems.append("plan_user_rounds_exceed_declared_limit")
    if declared_api_rounds is not None and plan_doc["api_rounds"] > declared_api_rounds:
        problems.append("plan_api_rounds_exceed_declared_limit")

    for key in PRICE_KEYS:
        raw = (os.environ.get(key) or "").strip()
        try:
            value = float(raw)
        except ValueError:
            problems.append(f"pricing_missing_or_invalid:{key}")
            continue
        if not math.isfinite(value) or value <= 0:
            problems.append(f"pricing_missing_or_invalid:{key}")

    if (os.environ.get(ADMISSION_FLAG) or "").strip().lower() not in {
        "1",
        "true",
        "on",
        "yes",
    }:
        problems.append("admission_not_enabled")

    ledger = (os.environ.get("LLM_SPEND_LEDGER_DB") or "").strip()
    if not ledger:
        problems.append("ledger_not_configured")
    elif not Path(ledger).is_absolute():
        problems.append("ledger_not_absolute")

    if not (os.environ.get("LLM_SPEND_EXPERIMENT_ID") or "").strip():
        problems.append("experiment_not_configured")

    cap = _effective_cap(problems)
    if cap is not None and cost_number is not None and cap > cost_number:
        # The guard is the thing that actually stops spending; a guard looser
        # than the declared envelope would make the declared limit decorative.
        problems.append(f"experiment_cap_exceeds_declared_limit:{cap}>{cost_number}")

    return {
        "ok": not problems,
        "problems": problems,
        "effective_cap_cny": cap,
        "checked_at": _utc_now(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument(
        "--plan",
        action="store_true",
        help="print the derived plan and send caps (default)",
    )
    parser.add_argument(
        "--validate-budget",
        action="store_true",
        help="check pricing, cap, ledger, admission and limits; still sends nothing",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="refused in this slice: arm execution is not wired yet",
    )
    args = parser.parse_args(argv)

    try:
        preview = load_preview(args.preview.resolve(), args.tasks.resolve())
    except ValueError as exc:
        print(f"preview rejected: {exc}")
        return 1
    plan_doc = plan(preview)

    if args.live:
        print(
            "refusing --live: arm execution is not wired in this slice; "
            "use --plan or --validate-budget"
        )
        return 2

    if args.validate_budget:
        result = validate_budget(preview, plan_doc)
        print(
            json.dumps(
                {**plan_doc, "budget_check": result},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if result["ok"] else 1

    print(json.dumps(plan_doc, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] if len(sys.argv) > 1 else None))
