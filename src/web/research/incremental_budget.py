"""Opt-in, task-derived grants with durable identity and no counter reset.

The per-goal resource vector and global limits must be supplied by a calibrated
deployment policy. There is deliberately no percentage or per-message default.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any

AXES = ("model_calls", "searches", "reads", "python_runs", "wall_seconds")


def load_incremental_policy() -> dict[str, dict[str, float]] | None:
    raw = os.getenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", "").strip()
    if not raw:
        return None
    policy = json.loads(raw)
    for section in ("initial", "per_goal", "limits"):
        if not isinstance(policy.get(section), dict) or set(policy[section]) != set(
            AXES
        ):
            raise ValueError(
                f"Incremental budget policy requires all resource axes in {section}"
            )
        for axis, value in policy[section].items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid incremental budget amount: {section}.{axis}")
            if axis != "wall_seconds" and int(value) != value:
                raise ValueError(
                    f"Incremental resource count must be an integer: {axis}"
                )
    if any(policy["initial"][axis] > policy["limits"][axis] for axis in AXES):
        raise ValueError("Initial budget cannot exceed its global limit")
    if policy["initial"]["python_runs"] or policy["per_goal"]["python_runs"]:
        raise ValueError(
            "This Deep executor has no Python tool; compute grants cannot be issued"
        )
    return policy


def initialize_budget(
    deep: dict[str, Any], policy: dict[str, dict[str, float]] | None
) -> None:
    if "incremental_budget" in deep or policy is None:
        return
    deep["incremental_budget"] = {
        "initial": dict(policy["initial"]),
        "per_goal": dict(policy["per_goal"]),
        "limits": dict(policy["limits"]),
        "grants": {},
        "consumed": dict.fromkeys(AXES, 0),
        # A planner invocation reserves one call even if its implementation is
        # deterministic; this is a conservative reservation, not token billing.
        "model_accounting": "planner_call_reservations",
    }


def authorize_goal(
    deep: dict[str, Any], *, steering_id: str, task_id: str
) -> dict[str, float]:
    ledger = deep.get("incremental_budget")
    if not isinstance(ledger, dict):
        return {}
    grants = ledger["grants"]
    if steering_id in grants:
        return dict(grants[steering_id]["authorized"])
    # Reuse of an existing task is not new work and must not mint another grant.
    if any(grant["task_id"] == task_id for grant in grants.values()):
        return {}
    authorized = {
        axis: min(
            ledger["per_goal"][axis],
            max(0, ledger["limits"][axis] - total_authorized(ledger, axis)),
        )
        for axis in AXES
    }
    grants[steering_id] = {
        "task_id": task_id,
        "requested": dict(ledger["per_goal"]),
        "authorized": authorized,
    }
    return authorized


def total_authorized(ledger: dict[str, Any], axis: str) -> float:
    return float(ledger["initial"][axis]) + sum(
        float(grant["authorized"][axis]) for grant in ledger["grants"].values()
    )


def remaining(deep: dict[str, Any], axis: str) -> float | None:
    ledger = deep.get("incremental_budget")
    if not isinstance(ledger, dict):
        return None
    return max(0.0, total_authorized(ledger, axis) - float(ledger["consumed"][axis]))


def consume(deep: dict[str, Any], axis: str, amount: float = 1) -> None:
    ledger = deep.get("incremental_budget")
    if isinstance(ledger, dict):
        ledger["consumed"][axis] += amount
