"""Resolve an explicit repair from saved source and preserve it across retries."""

from contextlib import nullcontext
import hashlib
import re
from typing import Any

from src.interactive_repair_budget import (
    InteractiveRepairBudget,
    current_repair_budget,
    repair_budget_scope,
)
from src.interactive_history import find_interactive_versions
from src.interactive_restore import RestoreRequest, resolve_interactive_restore


def resolve_repair(repository: Any, command: Any, parent: Any) -> dict[str, Any] | None:
    requested = command.interactive_repair
    saved = (
        parent.route_snapshot.get("interactive_repair") if parent is not None else None
    )
    if parent is not None:
        identity = {"id": saved["id"], "revision": saved["revision"]} if saved else None
        if requested is not None and requested != identity:
            raise ValueError("A repair retry cannot change its source")
        requested = identity
    if requested is None:
        return None
    if not isinstance(requested, dict) or set(requested) != {"id", "revision"}:
        raise ValueError("Repair accepts source identity only")
    request = RestoreRequest.from_payload(requested)
    if request is None:
        raise ValueError("Invalid repair source identity")
    source = resolve_interactive_restore(repository, command.thread_id, request)
    if not source.restorable or source.html is None:
        raise ValueError(f"Repair source unavailable: {source.status}")
    record = {
        "id": request.id,
        "revision": request.revision,
        "source_sha256": hashlib.sha256(source.html.encode()).hexdigest(),
        "capabilities": list(source.capabilities),
    }
    if saved is not None and record != saved:
        raise ValueError("Saved repair source changed")
    return record


def repair_policy(thread_id: str, record: dict[str, Any]) -> InteractiveRepairBudget:
    return InteractiveRepairBudget(
        thread_id=thread_id,
        component_id=record["id"],
        source_revision=record["revision"],
        source_sha256=record["source_sha256"],
        capabilities=tuple(record["capabilities"]),
    )


def repair_scope(thread_id: str, record: dict[str, Any] | None):
    if record is None:
        return nullcontext()
    policy = repair_policy(thread_id, record)
    if current_repair_budget() == policy:
        return nullcontext()
    return repair_budget_scope(policy)


def validate_repair_output(
    reply: str, route: dict[str, Any], repository: Any = None, thread_id: str = ""
) -> str:
    """Record document applicability, never semantic or browser success."""
    repair = route.get("interactive_repair")
    if not repair:
        return reply
    if repository is not None:
        from src.interactive_output import normalize_interactive_output

        request = RestoreRequest.from_payload(repair)
        outcome = (
            resolve_interactive_restore(repository, thread_id, request)
            if request
            else None
        )
        if (
            outcome
            and outcome.html
            and hashlib.sha256(outcome.html.encode()).hexdigest()
            == repair.get("source_sha256")
        ):
            reply = normalize_interactive_output(
                reply, outcome, (route.get("generation") or {}).get("finish_reason")
            )
    expected = (route.get("interactive_restore") or {}).get("expected_new_revision")
    versions = find_interactive_versions([{"role": "assistant", "content": reply}])
    reason = "missing_document"
    if (route.get("generation") or {}).get("finish_reason") != "stop":
        reason = "incomplete_generation"
    # Explicit repair delivers one component. Extra protocol fences can consume
    # the browser card limit before the target; do not infer their card types.
    # Conservatively reject even quoted protocol examples in this output mode.
    elif (
        len(re.findall(r"(?m)^ {0,3}(?:`{3,}|~{3,})[ \t]*study-ui[ \t]*\r?$", reply))
        > 1
    ):
        reason = "ambiguous_documents"
    elif len(versions) > 1:
        reason = "ambiguous_documents"
    elif versions:
        version = versions[0]
        if version.id != repair["id"]:
            reason = "component_mismatch"
        elif expected is None or version.revision != expected:
            reason = "revision_mismatch"
        elif version.capabilities != tuple(repair.get("capabilities", [])):
            reason = "capability_mismatch"
        else:
            reason = ""
    route["interactive_repair_result"] = {
        "status": "not_updated" if reason else "applicable_document",
        "reason": reason,
        "component_id": repair["id"],
        "expected_new_revision": expected,
    }
    if not reason:
        return reply
    fence = "`" * max(
        3, 1 + max((len(m.group()) for m in re.finditer(r"`+", reply)), default=0)
    )
    return (
        "**界面未更新：本次回答未提供与所选组件、目标版本及能力声明一致的完整可应用文档。**"
        "下面保留模型原答供查看；说明或代码片段不会自动应用。\n\n"
        + fence
        + "text\n"
        + reply
        + "\n"
        + fence
    )
