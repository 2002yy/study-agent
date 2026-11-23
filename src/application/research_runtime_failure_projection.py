"""Append a durable runtime failure against the current execution owner.

This projection does not checkpoint or recover the cursor. The executor keeps
ownership of persistence order and passes the current context on every call.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
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


@dataclass(frozen=True, slots=True)
class ActiveRuntimeFailureContext:
    """Record a runtime failure on the one current cursor/context owner.

    Constructing this object never snapshots a cursor, attempt number, or
    context. The legacy projection remains pure; assigning the resulting
    cursor happens only after successful failure construction. Checkpoints
    and budget admission remain the caller's responsibility.
    """

    live: ActiveRuntimeLiveValues

    def append(
        self,
        code: ResearchFailureCode,
        phase: RuntimePhase,
        *,
        logical_call_id: str = "",
        item_id: str = "",
        detail: str = "",
        provider_code: str = "",
        exception_type: str = "",
        attempt_id: str = "",
    ) -> None:
        self.live.set_cursor(
            with_appended_runtime_failure(
                self.live.current_cursor(),
                self.live.current_context(),
                code,
                phase,
                logical_call_id=logical_call_id,
                item_id=item_id,
                detail=detail,
                provider_code=provider_code,
                exception_type=exception_type,
                attempt_id=attempt_id,
            )
        )
