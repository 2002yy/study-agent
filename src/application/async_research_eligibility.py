"""Async Deep-1A eligibility predicate.

Defines **when a run may be started/resumed automatically**.  It is deliberately
conservative and pure so 1B's scheduler can call it unchanged, and so it can be
tested without a worker.

Rules (see ASYNC_DEEP_1A_IMPLEMENTATION.md):

* a cancellation is terminal — never automatically revived;
* an expired/exhausted authorization never starts anything (``paused`` waits for
  a new, explicit user grant);
* a ``failed`` run is only retryable for explicitly retryable reasons, never for
  permission, security or integrity failures;
* there must be real work left (pending plan task, unexecuted supplement, or an
  unfinished computation) and a lease must be acquirable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.repositories.research_authorization_repository import (
    ResearchAuthorization,
    is_within_deadline,
)

#: Failure reasons that a normal retry may pick up. Anything else (permission,
#: security, integrity, contract violations) must not be auto-retried.
RETRYABLE_FAILURE_REASONS = frozenset(
    {
        "",
        "providers_failed",
        "provider_failed",
        "search_candidates_only",
        "source_reading_failed",
        "no_public_sources",
        "chat_tool_loop_failed",
    }
)


def has_executable_work(run: Any) -> bool:
    """True when the checkpoint still has work the executor could do."""

    context = getattr(run, "research_context", None)
    deep = context.get("deep") if isinstance(context, dict) else None
    if not isinstance(deep, dict):
        # A run without a Deep plan always has its first round to do.
        return getattr(run, "status", "") in {"pending", "paused", "failed"}
    for task in deep.get("plan") or []:
        if isinstance(task, dict) and task.get("status") == "pending":
            return True
    for entry in deep.get("steering") or []:
        if isinstance(entry, dict) and entry.get("executed_in_round") is None:
            return True
    return False


def is_eligible(
    *,
    run: Any,
    grant: ResearchAuthorization | None,
    lease_available: bool,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Return ``(eligible, reason)``; ``reason`` is empty when eligible."""

    status = str(getattr(run, "status", ""))
    if status == "cancelled":
        return False, "cancelled_is_terminal"
    if grant is None or str(getattr(grant, "status", "")) != "active":
        return False, "no_active_authorization"
    if not is_within_deadline(grant, now=now or datetime.now(timezone.utc)):
        return False, "authorization_expired"
    if int(grant.max_spend_micros) - int(grant.reserved_micros) <= 0:
        return False, "authorization_exhausted"
    if status not in {"pending", "running", "paused", "failed"}:
        return False, f"status_not_eligible:{status}"
    if status == "failed":
        reason = str(getattr(run, "stop_reason", "") or "")
        if reason not in RETRYABLE_FAILURE_REASONS:
            return False, f"failure_not_retryable:{reason}"
    if not lease_available:
        return False, "lease_unavailable"
    if not has_executable_work(run):
        return False, "no_executable_work"
    return True, ""
