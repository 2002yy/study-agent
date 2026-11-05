"""Resolve an explicit repair from saved source and preserve it across retries."""

from contextlib import nullcontext
import hashlib
from typing import Any

from src.interactive_repair_budget import (
    InteractiveRepairBudget,
    current_repair_budget,
    repair_budget_scope,
)
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
