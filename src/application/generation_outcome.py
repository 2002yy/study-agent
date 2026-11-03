"""Per-answer provider termination evidence; separate from publication status."""

from __future__ import annotations

from typing import Any


def finish_outcome(reason: str | None) -> dict[str, str]:
    known = (
        reason
        if reason in {"stop", "length", "content_filter", "tool_calls", "function_call"}
        else "unknown"
    )
    status = {
        "stop": "completed",
        "length": "output_limit",
        "content_filter": "provider_blocked",
    }.get(known, "unknown")
    return {"status": status, "finish_reason": known}


def error_outcome(error: BaseException) -> dict[str, str]:
    # The transport preserves the SDK exception as __cause__; never infer a
    # timeout by searching a provider's error message or expose its raw payload.
    from openai import APITimeoutError, APIConnectionError

    cause: BaseException | None = error
    seen: set[int] = set()
    status = "error"
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, (TimeoutError, APITimeoutError)):
            status = "timeout"
            break
        if isinstance(cause, APIConnectionError):
            status = "connection_error"
        cause = cause.__cause__
    return {"status": status, "finish_reason": "unknown"}


def record_finish(route: dict[str, Any], reason: str | None) -> None:
    if route.get("generation", {}).get("status", "unknown") == "unknown":
        route["generation"] = finish_outcome(reason)
