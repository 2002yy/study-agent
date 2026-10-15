"""Bounded, explicit Deep plan edits; unsupported semantics are not acknowledged.

Free-form additions become research questions. Corrections must identify both
terms. Source policies, Python, and task replacement need separate executors.
"""

from __future__ import annotations

import re
from typing import Any


def steering_intent(content: str) -> dict[str, str]:
    if re.search(
        r"只[看用查].*官方|仅.*官方|official.only|别再搜|不要搜", content, re.I
    ):
        raise ValueError("来源限制尚未接入当前执行器，请停止后按新范围提问或排队下一轮")
    if re.search(r"python|代码|脚本", content, re.I):
        # Arbitrary code execution stays closed; only the bounded compute tools
        # run, and only through the isolated executor.
        raise ValueError("当前不支持提交可执行代码；如需计算请给出参数并说“按新配置重算”")
    if re.search(r"重新计算|重算|重新画|重画|recompute", content, re.I):
        # A recompute is now a legal supplement target: it supersedes prior
        # results and lets the bounded compute decision run again.
        return {"kind": "recompute"}
    if re.search(r"先放下|换个问题|换一个|停止研究|取消研究|回答完再", content):
        raise ValueError("请使用停止或排队下一轮，任务替换不属于增量转向")
    if re.search(r"解释.*简单|简短一点|简洁一点|少写一点", content):
        raise ValueError("措辞调整不属于检索目标，请排队为下一轮回答要求")
    match = re.search(
        r"不是\s*([^，,；;。]+?)[，,；;\s]*(?:而)?是\s*([^，,；;。]+)", content
    )
    if not match:
        match = re.search(r"not\s+(.+?)\s+but\s+(.+)", content, re.I)
    if match:
        return {"kind": "correction", "old": match[1].strip(), "new": match[2].strip()}
    reversed_match = re.search(
        r"(?:刚才|应该)?是\s*([^，,；;。]+?)[，,；;\s]+不是\s*([^，,；;。]+)", content
    )
    if reversed_match:
        return {
            "kind": "correction",
            "old": reversed_match[2].strip(),
            "new": reversed_match[1].strip(),
        }
    if re.search(r"不是|改成|换成|instead.of|replace", content, re.I):
        raise ValueError("这条约束替换还不够明确，请写成“不是 X，是 Y”或排队下一轮")
    return {"kind": "addition"}


def revise_deep_plan(
    deep: dict[str, Any], entry: dict[str, Any], *, query: str, cap: int
) -> bool:
    """Install a task dependency before exposing an applied receipt."""
    plan = deep.setdefault("plan", [])
    if len(plan) >= cap:
        return False
    intent = steering_intent(str(entry.get("content", "")))
    entry_id = str(entry.get("id") or entry.get("received_at") or len(plan))
    effective = str(deep.get("effective_query") or query)
    if intent["kind"] == "correction":
        old, new = intent["old"], intent["new"]
        if old.casefold() not in effective.casefold():
            entry["not_applied_reason"] = "correction_target_not_in_current_question"
            return False
        effective = re.sub(re.escape(old), lambda _: new, effective, flags=re.I)
        deep["effective_query"] = effective
        replacements = deep.setdefault("corrections", [])
        replacements.append({"old": old, "new": new, "steering_id": entry_id})
        for task in plan:
            if task.get("status") == "pending":
                task["sub_question"] = re.sub(
                    re.escape(old),
                    lambda _: new,
                    str(task.get("sub_question", "")),
                    flags=re.I,
                )
                task["steering_ids"] = [*task.get("steering_ids", []), entry_id]
    if intent["kind"] == "recompute":
        # A recompute is a legal supplement target now that the bounded compute
        # tools exist: keep the execution history but retire the old results so
        # the next compute decision publishes a new revision.
        entry["kind"] = "recompute"
        entry["task_id"] = f"recompute_{entry_id}"
        deep["recompute_requested"] = entry_id
        revision = int(deep.get("recompute_epoch") or 0) + 1
        deep["recompute_epoch"] = revision
        computations = deep.get("computations")
        if isinstance(computations, list):
            deep["computations"] = [
                {**item, "status": "superseded", "superseded_by_revision": revision}
                if isinstance(item, dict) and item.get("status") == "succeeded"
                else item
                for item in computations
            ]
        return True
    question = (
        effective
        if intent["kind"] == "correction"
        else f"{effective}；新增研究目标：{entry['content']}"
    )
    task_id = f"steer_{entry_id}"
    existing = next(
        (task for task in plan if task.get("sub_question") == question[:4000]), None
    )
    if existing:
        entry["task_id"] = existing["task_id"]
        entry["kind"] = intent["kind"]
        existing["steering_ids"] = [*existing.get("steering_ids", []), entry_id]
        if existing.get("status") == "done":
            entry["executed_in_round"] = existing.get("round")
        return True
    plan.append(
        {
            "task_id": task_id,
            "sub_question": question[:4000],
            "status": "pending",
            "round": None,
            "steering_ids": [entry_id],
        }
    )
    entry["task_id"] = task_id
    entry["kind"] = intent["kind"]
    return True
