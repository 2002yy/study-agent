"""Append a durable runtime failure against explicitly supplied current state.

This projection does not checkpoint or recover the cursor. The executor keeps
ownership of persistence order and passes the current context on every call.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.web.research.failure_contracts import ResearchFailureCode
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimePhase,
    append_runtime_failure,
    build_runtime_failure,
    runtime_failure_id,
    runtime_failure_id_unattached,
)


def with_appended_runtime_failure(
    cursor: ResearchRuntimeCursor,
    context: dict[str, Any],
    code: ResearchFailureCode,
    phase: RuntimePhase,
    *,
    logical_call_id: str = "",
    item_id: str = "",
    detail: str = "",
    provider_code: str = "",
    exception_type: str = "",
    attempt_id: str = "",
) -> ResearchRuntimeCursor:
    """Preserve failure identity, append deduplication and lazy attempt fallback."""

    durable_attempt_id = attempt_id or f"run-attempt:{context['run_attempt']}"
    failure_id = (
        runtime_failure_id(logical_call_id=logical_call_id, code=code)
        if logical_call_id
        else runtime_failure_id_unattached(
            phase=phase,
            item_id=item_id,
            attempt_id=durable_attempt_id,
            code=code,
        )
    )
    failure = build_runtime_failure(
        failure_id=failure_id,
        code=code,
        phase=phase,
        item_id=item_id,
        detail=detail,
        provider_code=provider_code,
        exception_type=exception_type,
        attempt_id=durable_attempt_id,
    )
    return replace(
        cursor,
        failures=append_runtime_failure(cursor.failures, failure),
    )
