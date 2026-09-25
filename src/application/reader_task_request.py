# -*- coding: utf-8 -*-
"""§143-P1 external request-surface binding.

Canonical rule (docs/PROJECT_STATUS.md §143.151):

> the **application request/task DTO** is the single canonical surface.
> API request fields, frozen task manifests and UI toggles are only 1:1 adapters
> into it; none of them owns routing semantics.

Frozen boundary contract:

* external serialised form is ``reader_capabilities: list[str]`` with the closed
  values ``"JS_RENDER"`` / ``"SESSION_STATE"``;
* a missing field, ``None`` and ``[]`` are all exactly **no hint**;
* unknown values, bare strings and wrong types are boundary validation errors;
* the canonical request is constructed as an internal frozen set of capabilities;
* ``hint_source`` is **assigned by the adapter** from a closed vocabulary
  (``REQUEST_FIELD`` / ``TASK_MANIFEST`` / ``UI_TOGGLE``) - an external payload
  that tries to supply it is rejected;
* ``SESSION_STATE`` requires its companion session/setup inputs on the same
  request, checked *before* routing;
* runtime/planner/LLM must never mutate or infer these capabilities;
* when the hint feature flag is off the field is still accepted and recorded,
  but routing effect is zero (no schema churn between rollout states).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.application.reader_hint_routing import (
    SESSION_STATE,
    ReaderHintError,
    parse_reader_capabilities,
    run_reader_with_hints,
)

HINT_SOURCE_REQUEST_FIELD = "REQUEST_FIELD"
HINT_SOURCE_TASK_MANIFEST = "TASK_MANIFEST"
HINT_SOURCE_UI_TOGGLE = "UI_TOGGLE"

ALLOWED_HINT_SOURCES: frozenset[str] = frozenset(
    {HINT_SOURCE_REQUEST_FIELD, HINT_SOURCE_TASK_MANIFEST, HINT_SOURCE_UI_TOGGLE}
)

#: External payload key that only adapters may own. Presence here is a spoof.
_HINT_SOURCE_KEY = "hint_source"


class ReaderRequestError(ReaderHintError):
    """Boundary validation error for a canonical reader task request."""


@dataclass(frozen=True)
class ReaderTaskRequest:
    """The single canonical request object P1 routing consumes."""

    url: str
    reader_capabilities: frozenset[str] = field(default_factory=frozenset)
    session_id: str | None = None
    setup_url: str | None = None
    hint_source: str = HINT_SOURCE_REQUEST_FIELD


def parse_reader_task_request(
    raw: Mapping[str, Any] | None,
    *,
    hint_source: str,
) -> ReaderTaskRequest:
    """Validate an external payload into the canonical request.

    ``hint_source`` is supplied by the calling adapter, never read from ``raw``.
    """

    if hint_source not in ALLOWED_HINT_SOURCES:
        raise ReaderRequestError(f"unknown hint_source: {hint_source!r}")
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ReaderRequestError("reader task request must be a mapping")
    if _HINT_SOURCE_KEY in raw:
        # caller must not be able to spoof where the hint came from
        raise ReaderRequestError("hint_source is adapter-owned and must not be supplied")

    capabilities = frozenset(parse_reader_capabilities(raw.get("reader_capabilities", [])))
    session_id = raw.get("session_id")
    setup_url = raw.get("setup_url")
    if session_id is not None and not isinstance(session_id, str):
        raise ReaderRequestError("session_id must be a string")
    if setup_url is not None and not isinstance(setup_url, str):
        raise ReaderRequestError("setup_url must be a string")

    if SESSION_STATE in capabilities and not (session_id or setup_url):
        # rejected before routing/read: the specialist must not invent a login flow
        raise ReaderRequestError("session_inputs_missing")

    return ReaderTaskRequest(
        url=str(raw.get("url") or ""),
        reader_capabilities=capabilities,
        session_id=session_id or None,
        setup_url=setup_url or None,
        hint_source=hint_source,
    )


def from_request_field(raw: Mapping[str, Any] | None) -> ReaderTaskRequest:
    return parse_reader_task_request(raw, hint_source=HINT_SOURCE_REQUEST_FIELD)


def from_task_manifest(raw: Mapping[str, Any] | None) -> ReaderTaskRequest:
    return parse_reader_task_request(raw, hint_source=HINT_SOURCE_TASK_MANIFEST)


def from_ui_toggle(raw: Mapping[str, Any] | None) -> ReaderTaskRequest:
    return parse_reader_task_request(raw, hint_source=HINT_SOURCE_UI_TOGGLE)


def run_reader_task(
    request: ReaderTaskRequest,
    *,
    default_kwargs: Mapping[str, Any] | None = None,
    specialist_kwargs: Mapping[str, Any] | None = None,
    hints_enabled: bool | None = None,
    specialist_config_ok: bool | None = None,
) -> dict[str, Any]:
    """Route one canonical request through the P1 reader entry."""

    return run_reader_with_hints(
        url=request.url,
        reader_capabilities=request.reader_capabilities,
        hint_source=request.hint_source,
        session_id=request.session_id,
        setup_url=request.setup_url,
        hints_enabled=hints_enabled,
        specialist_config_ok=specialist_config_ok,
        default_kwargs=default_kwargs,
        specialist_kwargs=specialist_kwargs,
    )


__all__ = [
    "ALLOWED_HINT_SOURCES",
    "HINT_SOURCE_REQUEST_FIELD",
    "HINT_SOURCE_TASK_MANIFEST",
    "HINT_SOURCE_UI_TOGGLE",
    "ReaderRequestError",
    "ReaderTaskRequest",
    "from_request_field",
    "from_task_manifest",
    "from_ui_toggle",
    "parse_reader_task_request",
    "run_reader_task",
]
