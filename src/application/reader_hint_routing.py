# -*- coding: utf-8 -*-
"""§143-P1: explicit structured reader-capability hint routing.

Frozen contract (docs/PROJECT_STATUS.md §143.139):

* the only inputs a hint may have are ``JS_RENDER`` and ``SESSION_STATE``;
* a hint may **only** originate from an explicit caller/task declaration
  (``reader_capabilities``); runtime/planner code must never derive it from URL,
  metadata, content, default-read outcomes or prior specialist results;
* with no hint, behaviour is exactly the current P0/P4 default read;
* the hint is *routing intent*, not a capability guarantee, and cannot bypass
  specialist health/eligibility/readiness;
* when a hint is honored it selects the Crawl4AI specialist first; when the
  specialist is unavailable or yields nothing usable, the existing default read
  runs as best-effort fallback and the hint is recorded as unhonored;
* ``SESSION_STATE`` only consumes existing session/setup inputs; when they are
  missing the call is rejected before any read;
* combined hints still invoke the specialist exactly once;
* PDF is explicitly outside P1.

The gate ``EXPLICIT_READER_HINTS_ENABLED`` defaults to **off**: parsing and
provenance always work, but routing effect is zero until an operator enables it.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping

from src.application.active_research_runtime import run_single_read_measurement
from src.web.research.crawl4ai_specialist import (
    crawl4ai_specialist_status,
    invoke_crawl4ai_specialist,
)

JS_RENDER = "JS_RENDER"
SESSION_STATE = "SESSION_STATE"

#: The closed v1 vocabulary. Anything else is a validation error, never ignored.
ALLOWED_READER_CAPABILITIES: frozenset[str] = frozenset({JS_RENDER, SESSION_STATE})

EXPLICIT_HINTS_ENABLED_ENV = "EXPLICIT_READER_HINTS_ENABLED"

ROUTE_DEFAULT = "default"
ROUTE_SPECIALIST = "specialist"
ROUTE_SPECIALIST_FALLBACK = "specialist_fallback"
ROUTE_UNSATISFIED = "unsatisfied"

REASON_NO_HINT = "no_hint"
REASON_HINTS_DISABLED = "hints_disabled"
REASON_SESSION_INPUTS_MISSING = "session_inputs_missing"
REASON_SPECIALIST_UNAVAILABLE = "specialist_unavailable"
REASON_SPECIALIST_NO_CONTENT = "specialist_no_usable_content"


class ReaderHintError(ValueError):
    """An unknown / malformed reader-capability hint (fail-closed)."""


def explicit_reader_hints_enabled() -> bool:
    return (os.getenv(EXPLICIT_HINTS_ENABLED_ENV) or "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }


def parse_reader_capabilities(value: Any) -> tuple[str, ...]:
    """Validate an explicit hint value into a deduplicated ordered tuple.

    Accepts ``None`` (no hint) or a non-string iterable of strings. A bare
    string is rejected: it would be silently exploded into characters.
    """

    if value is None:
        return ()
    if isinstance(value, str):
        raise ReaderHintError("reader_capabilities must be a set/list of capability values")
    try:
        items = list(value)
    except TypeError as exc:
        raise ReaderHintError("reader_capabilities must be an iterable") from exc

    parsed: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ReaderHintError(f"reader capability must be a string: {item!r}")
        capability = item.strip()
        if capability not in ALLOWED_READER_CAPABILITIES:
            raise ReaderHintError(f"unknown reader capability: {item!r}")
        if capability not in parsed:
            parsed.append(capability)
    return tuple(parsed)


def resolve_reader_route(
    reader_capabilities: Any,
    *,
    hints_enabled: bool,
    specialist_config_ok: bool,
    session_inputs_present: bool,
) -> dict[str, Any]:
    """Pure routing decision over validated hints (no I/O, no environment)."""

    requested = parse_reader_capabilities(reader_capabilities)
    base = {"requested_reader_capabilities": list(requested)}

    if not requested:
        return {**base, "route": ROUTE_DEFAULT, "hint_honored": True, "reason": REASON_NO_HINT}
    if not hints_enabled:
        return {
            **base,
            "route": ROUTE_DEFAULT,
            "hint_honored": False,
            "reason": REASON_HINTS_DISABLED,
        }
    if SESSION_STATE in requested and not session_inputs_present:
        # rejected before any read: the specialist must not invent a login flow
        return {
            **base,
            "route": ROUTE_UNSATISFIED,
            "hint_honored": False,
            "reason": REASON_SESSION_INPUTS_MISSING,
        }
    if not specialist_config_ok:
        return {
            **base,
            "route": ROUTE_DEFAULT,
            "hint_honored": False,
            "reason": REASON_SPECIALIST_UNAVAILABLE,
        }
    return {**base, "route": ROUTE_SPECIALIST, "hint_honored": True, "reason": ""}


def _specialist_backend_path(specialist: Mapping[str, Any]) -> list[str]:
    backend = str(specialist.get("actual_backend") or "")
    return [backend] if backend else []


def _default_backend_path(default: Mapping[str, Any]) -> list[str]:
    path = default.get("backend_path")
    return [str(item) for item in path] if isinstance(path, list) else []


def run_reader_with_hints(
    *,
    url: str,
    reader_capabilities: Any = None,
    hint_source: str = "explicit_request",
    session_id: str | None = None,
    setup_url: str | None = None,
    hints_enabled: bool | None = None,
    specialist_config_ok: bool | None = None,
    default_kwargs: Mapping[str, Any] | None = None,
    specialist_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Production read entry that honours explicit reader-capability hints.

    ``default_kwargs`` / ``specialist_kwargs`` are forwarded verbatim to the
    default measurement entry and the specialist seam respectively; this
    function itself never derives a hint from content.
    """

    enabled = explicit_reader_hints_enabled() if hints_enabled is None else hints_enabled
    if specialist_config_ok is None:
        specialist_config_ok = bool(crawl4ai_specialist_status().get("config_ok"))
    session_inputs_present = bool(session_id or setup_url)

    route = resolve_reader_route(
        reader_capabilities,
        hints_enabled=enabled,
        specialist_config_ok=specialist_config_ok,
        session_inputs_present=session_inputs_present,
    )

    provenance: dict[str, Any] = {
        "route": route["route"],
        "requested_reader_capabilities": route["requested_reader_capabilities"],
        "hint_source": str(hint_source or ""),
        "hint_honored": bool(route["hint_honored"]),
        "hint_unhonored_reason": route["reason"],
        "actual_backend_path": [],
        "specialist": None,
        "default": None,
    }

    if route["route"] == ROUTE_UNSATISFIED:
        return provenance

    default_kwargs = dict(default_kwargs or {})
    specialist_kwargs = dict(specialist_kwargs or {})

    if route["route"] == ROUTE_SPECIALIST:
        specialist = _SPECIALIST_READER(
            url=url,
            session_id=session_id,
            setup_url=setup_url,
            **specialist_kwargs,
        )
        provenance["specialist"] = specialist
        if specialist.get("specialist_available") and specialist.get("usable_content"):
            provenance["actual_backend_path"] = _specialist_backend_path(specialist)
            return provenance
        # specialist could not deliver -> existing default read as best-effort
        default = _DEFAULT_READER(url=url, **default_kwargs)
        provenance["default"] = default
        provenance["route"] = ROUTE_SPECIALIST_FALLBACK
        provenance["hint_honored"] = False
        provenance["hint_unhonored_reason"] = (
            str(specialist.get("unavailable_reason") or "")
            or REASON_SPECIALIST_NO_CONTENT
        )
        provenance["actual_backend_path"] = _default_backend_path(default)
        return provenance

    default = _DEFAULT_READER(url=url, **default_kwargs)
    provenance["default"] = default
    provenance["actual_backend_path"] = _default_backend_path(default)
    return provenance


#: Module-level indirections so tests can inject fakes without a real runtime.
_DEFAULT_READER: Callable[..., Any] = run_single_read_measurement
_SPECIALIST_READER: Callable[..., Any] = invoke_crawl4ai_specialist


__all__ = [
    "ALLOWED_READER_CAPABILITIES",
    "EXPLICIT_HINTS_ENABLED_ENV",
    "JS_RENDER",
    "SESSION_STATE",
    "ReaderHintError",
    "explicit_reader_hints_enabled",
    "parse_reader_capabilities",
    "resolve_reader_route",
    "run_reader_with_hints",
]
