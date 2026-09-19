"""Injectable active-search gateway for the Research Quality Engine.

This adapter deliberately does not decide rollout. ``WebLookupService`` keeps
its legacy gateway by default; a later dispatch slice may inject this class only
for a Claim Engine active run. Search uses the research-only multi-provider
policy while reads continue through the existing ``ResearchWebGateway`` reader.

Per-call audit intentionally excludes raw query text, result payloads, snippets,
and page content. It is safe to checkpoint later without turning telemetry into
a second evidence store.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from src.web.research.provider_search import ResearchProviderSearch
from src.web.research_gateway import ResearchWebGateway

_PROVIDER_AUDIT_FIELDS = (
    "provider",
    "attempt",
    "status",
    "reason",
    "result_count",
    "elapsed_seconds",
    "query_sha256",
    "query_chars",
)
_PROVIDER_OUTCOME_FIELDS = (
    "provider",
    "status",
    "reason",
    "attempts",
    "result_count",
)
_PENDING_AUDIT_CAP = 32


class ResearchSearchExact(Protocol):
    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> Mapping[str, Any]: ...


class ResearchReadGateway(Protocol):
    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ActiveSearchCallAudit:
    status: str
    reason: str
    providers_attempted: tuple[str, ...]
    provider_errors: tuple[str, ...]
    provider_audits: tuple[dict[str, Any], ...]
    provider_outcomes: tuple[dict[str, Any], ...]
    searched_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "providers_attempted": list(self.providers_attempted),
            "provider_errors": list(self.provider_errors),
            "provider_audits": [dict(item) for item in self.provider_audits],
            "provider_outcomes": [dict(item) for item in self.provider_outcomes],
            "searched_at": self.searched_at,
        }


class ActiveResearchGateway:
    """Existing WebLookup gateway shape backed by all-enabled-provider search.

    Construction is explicit so merely importing this module cannot activate the
    new search policy. ``search()`` matches the legacy service contract;
    ``search_detailed()`` preserves the structured provider payload for the
    later checkpoint/dispatch slice.
    """

    def __init__(
        self,
        *,
        search_backend: ResearchSearchExact | None = None,
        read_gateway: ResearchReadGateway | None = None,
    ) -> None:
        self._search_backend = search_backend or ResearchProviderSearch()
        self._read_gateway = read_gateway or ResearchWebGateway()
        self._backend_accepts_deadline = _accepts_deadline(self._search_backend)
        self._read_gateway_accepts_timeout = read_gateway_accepts_timeout(
            self._read_gateway
        )
        self._last_audit: ActiveSearchCallAudit | None = None
        self._pending_audits: list[dict[str, Any] | None] = []
        self._warnings: list[dict[str, str]] = []

    def search_detailed(
        self,
        query: str,
        *,
        max_items: int = 10,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        self._last_audit = None
        self._warnings = []
        try:
            if deadline is not None and self._backend_accepts_deadline:
                payload = cast(Any, self._search_backend).search_exact(
                    query,
                    max_results=max_items,
                    deadline=deadline,
                )
            else:
                payload = self._search_backend.search_exact(query, max_results=max_items)
            if not isinstance(payload, Mapping):
                raise ValueError("research search backend must return a mapping")
            snapshot = dict(payload)
            self._last_audit = _audit_from_payload(snapshot)
            self._warnings = [
                {
                    "source": "research_multi_provider",
                    "error_type": "provider_error",
                    "message": error,
                }
                for error in self._last_audit.provider_errors
            ]
            return snapshot
        finally:
            self._pending_audits.append(self.last_search_audit())
            if len(self._pending_audits) > _PENDING_AUDIT_CAP:
                self._pending_audits = self._pending_audits[-_PENDING_AUDIT_CAP:]

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        payload = self.search_detailed(query, max_items=max_items)
        status = _bounded_text(payload.get("status"), 100)
        if status == "invalid_query":
            raise ValueError("Web lookup query is required")
        if status == "unavailable":
            raise RuntimeError(
                _bounded_text(payload.get("reason"), 200) or "web_search_unavailable"
            )

        normalized: list[dict[str, Any]] = []
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            return normalized
        for raw in raw_results:
            if not isinstance(raw, Mapping):
                continue
            record = dict(raw)
            if record.get("url") and not record.get("link"):
                record["link"] = record["url"]
            if record.get("snippet") and not record.get("search_excerpt"):
                record["search_excerpt"] = record["snippet"]
            normalized.append(record)
        return normalized

    def read(
        self,
        url: str,
        *,
        max_chars: int = 6000,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        # The shared research-window deadline is forwarded only to gateways
        # that accept it; legacy doubles keep the previous signature.
        # §48 diagnostic (default off): bounded fetch-layer retries wrap the
        # read; success-path behaviour and content semantics are unchanged.
        from src.web.research.read_retry import read_retry_enabled, read_with_bounded_retry

        def _inner(target: str) -> Mapping[str, Any]:
            if timeout is not None and self._read_gateway_accepts_timeout:
                return cast(Any, self._read_gateway).read(
                    target,
                    max_chars=max_chars,
                    timeout=timeout,
                )
            return self._read_gateway.read(target, max_chars=max_chars)

        if read_retry_enabled():
            return read_with_bounded_retry(url, read_fn=_inner)
        return dict(_inner(url) or {})

    def warnings(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._warnings]

    def last_search_audit(self) -> dict[str, Any] | None:
        if self._last_audit is None:
            return None
        return self._last_audit.to_dict()

    def drain_search_audits(self) -> list[dict[str, Any] | None]:
        pending = self._pending_audits
        self._pending_audits = []
        return [dict(item) if item is not None else None for item in pending]


def _audit_from_payload(payload: Mapping[str, Any]) -> ActiveSearchCallAudit:
    return ActiveSearchCallAudit(
        status=_bounded_text(payload.get("status"), 100),
        reason=_bounded_text(payload.get("reason"), 200),
        providers_attempted=_strings(payload.get("providers_attempted"), limit=12),
        provider_errors=_strings(payload.get("provider_errors"), limit=24),
        provider_audits=_mapping_tuple(
            payload.get("provider_audits"),
            fields=_PROVIDER_AUDIT_FIELDS,
            limit=24,
        ),
        provider_outcomes=_mapping_tuple(
            payload.get("provider_outcomes"),
            fields=_PROVIDER_OUTCOME_FIELDS,
            limit=12,
        ),
        searched_at=_bounded_text(payload.get("searched_at"), 100),
    )


def _mapping_tuple(
    value: Any,
    *,
    fields: tuple[str, ...],
    limit: int,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        {
            field: item[field]
            for field in fields
            if field in item
            and isinstance(item[field], (str, int, float, bool, type(None)))
        }
        for item in value[:limit]
        if isinstance(item, Mapping)
    )


def _strings(value: Any, *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        dict.fromkeys(
            text
            for item in value[:limit]
            if (text := _bounded_text(item, 300))
        )
    )


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _accepts_deadline(backend: ResearchSearchExact) -> bool:
    """Return True only when the backend's search_exact accepts ``deadline``.

    Keeps injected legacy backends (and test doubles) working unchanged while the
    deadline-aware production backend receives the stage deadline.
    """

    try:
        parameters = inspect.signature(backend.search_exact).parameters
    except (AttributeError, TypeError, ValueError):
        return False
    return "deadline" in parameters


def read_gateway_accepts_timeout(gateway: object) -> bool:
    """Return whether a read gateway can honour a shared read timeout.

    Legacy gateways (and test doubles) that only accept ``max_chars`` keep
    working; the caller then falls back to the gateway's own default timeout.
    """

    try:
        parameters = inspect.signature(gateway.read).parameters  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError):
        return False
    return "timeout" in parameters


__all__ = [
    "ActiveResearchGateway",
    "ActiveSearchCallAudit",
    "read_gateway_accepts_timeout",
]
