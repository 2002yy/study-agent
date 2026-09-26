from __future__ import annotations

import json
from typing import Any

import pytest

from src.web.research.active_adapter import ActiveResearchGateway


class FakeSearchBackend:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, int]] = []

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        self.calls.append((query, max_results))
        return self.payloads.pop(0)


class FakeReadGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        self.calls.append((url, max_chars))
        return {"ok": True, "content": "body"}


def _payload(
    *,
    status: str = "ok",
    reason: str = "results_found",
    provider: str = "bing_rss",
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "query": "raw query must not enter audit",
        "results": [
            {
                "title": "Result",
                "url": "https://example.test/item",
                "snippet": "result body must not enter audit",
                "provider": provider,
                "providers": [provider],
            }
        ],
        "providers_attempted": ["searxng", "bing_rss", "duckduckgo_html"],
        "provider_errors": ["searxng:timeout"],
        "provider_audits": [
            {
                "provider": "searxng",
                "attempt": 1,
                "status": "failed",
                "reason": "timeout",
                "result_count": 0,
                "elapsed_seconds": 1.25,
                "query_sha256": "digest-placeholder",
                "query_chars": 31,
                "query": "must be dropped",
                "results": ["must be dropped"],
                "snippet": "must be dropped",
            }
        ],
        "provider_outcomes": [
            {
                "provider": provider,
                "status": "ok",
                "reason": "results_found",
                "attempts": 1,
                "result_count": 1,
                "query": "must be dropped",
            }
        ],
        "searched_at": "2026-08-27T08:00:00+00:00",
    }


def test_active_gateway_preserves_legacy_search_shape_and_provider_policy_call() -> None:
    backend = FakeSearchBackend([_payload(status="partial", reason="results_with_provider_failures")])
    gateway = ActiveResearchGateway(search_backend=backend)

    results = gateway.search("focused query", max_items=4)

    assert backend.calls == [("focused query", 4)]
    assert results == [
        {
            "title": "Result",
            "url": "https://example.test/item",
            "link": "https://example.test/item",
            "snippet": "result body must not enter audit",
            "search_excerpt": "result body must not enter audit",
            "provider": "bing_rss",
            "providers": ["bing_rss"],
        }
    ]
    assert gateway.warnings() == [
        {
            "source": "research_multi_provider",
            "error_type": "provider_error",
            "message": "searxng:timeout",
        }
    ]


def test_per_call_audit_whitelists_telemetry_and_excludes_content() -> None:
    backend = FakeSearchBackend([_payload()])
    gateway = ActiveResearchGateway(search_backend=backend)

    detailed = gateway.search_detailed("sensitive raw query", max_items=5)
    audit = gateway.last_search_audit()

    assert detailed["query"] == "raw query must not enter audit"
    assert detailed["results"]
    assert audit is not None
    assert audit["providers_attempted"] == [
        "searxng",
        "bing_rss",
        "duckduckgo_html",
    ]
    assert audit["provider_errors"] == ["searxng:timeout"]
    assert audit["provider_audits"] == [
        {
            "provider": "searxng",
            "attempt": 1,
            "status": "failed",
            "reason": "timeout",
            "result_count": 0,
            "elapsed_seconds": 1.25,
            "query_sha256": "digest-placeholder",
            "query_chars": 31,
        }
    ]
    assert audit["provider_outcomes"] == [
        {
            "provider": "bing_rss",
            "status": "ok",
            "reason": "results_found",
            "attempts": 1,
            "result_count": 1,
        }
    ]
    serialized = json.dumps(audit, ensure_ascii=False)
    for forbidden in (
        "sensitive raw query",
        "raw query must not enter audit",
        "result body must not enter audit",
        "must be dropped",
    ):
        assert forbidden not in serialized


def test_audit_and_warnings_are_replaced_per_search_call() -> None:
    first = _payload(status="partial", reason="results_with_provider_failures")
    second = _payload(provider="duckduckgo_html")
    second["provider_errors"] = []
    second["providers_attempted"] = ["duckduckgo_html"]
    second["provider_audits"] = []
    second["provider_outcomes"] = [
        {
            "provider": "duckduckgo_html",
            "status": "ok",
            "reason": "results_found",
            "attempts": 1,
            "result_count": 1,
        }
    ]
    backend = FakeSearchBackend([first, second])
    gateway = ActiveResearchGateway(search_backend=backend)

    gateway.search("first")
    assert gateway.warnings()
    gateway.search("second")

    audit = gateway.last_search_audit()
    assert audit is not None
    assert audit["providers_attempted"] == ["duckduckgo_html"]
    assert audit["provider_errors"] == []
    assert gateway.warnings() == []


@pytest.mark.parametrize(
    ("status", "reason", "error_type"),
    [
        ("invalid_query", "empty_query", ValueError),
        ("unavailable", "providers_failed", RuntimeError),
    ],
)
def test_active_gateway_preserves_legacy_failure_contract(
    status: str,
    reason: str,
    error_type: type[Exception],
) -> None:
    payload = _payload(status=status, reason=reason)
    payload["results"] = []
    backend = FakeSearchBackend([payload])
    gateway = ActiveResearchGateway(search_backend=backend)

    with pytest.raises(error_type):
        gateway.search("query")

    assert gateway.last_search_audit() is not None


def test_active_gateway_reuses_existing_reader() -> None:
    reader = FakeReadGateway()
    gateway = ActiveResearchGateway(
        search_backend=FakeSearchBackend([_payload()]),
        read_gateway=reader,
    )

    result = gateway.read("https://example.test/article", max_chars=1234)

    assert result == {"ok": True, "content": "body"}
    assert reader.calls == [("https://example.test/article", 1234)]


class DeadlineSearchBackend:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.deadlines: list[float | None] = []

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        self.deadlines.append(deadline)
        return self.payload


def test_deadline_is_forwarded_only_to_deadline_aware_backend() -> None:
    deadline_backend = DeadlineSearchBackend(_payload())
    deadline_gateway = ActiveResearchGateway(search_backend=deadline_backend)
    deadline_gateway.search_detailed("query", deadline=123.5)
    assert deadline_backend.deadlines == [123.5]

    legacy_backend = FakeSearchBackend([_payload()])
    legacy_gateway = ActiveResearchGateway(search_backend=legacy_backend)
    legacy_gateway.search_detailed("query", deadline=123.5)
    assert legacy_backend.calls == [("query", 10)]
    assert legacy_gateway.last_search_audit() is not None


class DeadlineReadGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float | None]] = []

    def read(
        self,
        url: str,
        *,
        max_chars: int = 6000,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append((url, max_chars, timeout))
        return {"ok": True, "content": "body"}


def test_read_timeout_is_forwarded_only_to_timeout_aware_gateway() -> None:
    """Evidence reads share the research-window deadline when supported."""

    deadline_reader = DeadlineReadGateway()
    deadline_gateway = ActiveResearchGateway(read_gateway=deadline_reader)
    deadline_gateway.read("https://example.test/article", max_chars=1234, timeout=3.5)
    assert deadline_reader.calls == [("https://example.test/article", 1234, 3.5)]

    legacy_reader = FakeReadGateway()
    legacy_gateway = ActiveResearchGateway(read_gateway=legacy_reader)
    result = legacy_gateway.read(
        "https://example.test/article", max_chars=1234, timeout=3.5
    )
    assert result == {"ok": True, "content": "body"}
    assert legacy_reader.calls == [("https://example.test/article", 1234)]
