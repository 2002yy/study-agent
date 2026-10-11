from __future__ import annotations

import pytest

from src.web.research.discovery import DiscoveryRequest, LegacyDiscoveryAdapter
from src.web.research.platform_capabilities import (
    PlatformBatch, PlatformHit, PlatformRequest, platform_capability_registry, validate_platform_batch,
)


def test_legacy_adapter_keeps_original_query_deadline_limit_and_does_not_read():
    calls = []

    class Legacy:
        def search_exact(self, query, **kwargs):
            calls.append((query, kwargs))
            return {"status": "ok", "results": [{"url": "https://example.org/docs#section",
                    "title": "Docs", "snippet": "candidate only", "providers": ["searxng", "bing"]}]}

    request = DiscoveryRequest("原始问题", "official_docs", 8, 123.0)
    result = LegacyDiscoveryAdapter(Legacy()).search(request)
    assert calls == [("原始问题", {"max_results": 8, "deadline": 123.0})]
    assert result.hits[0].canonical_url == "https://example.org/docs"
    assert result.hits[0].provider == "searxng"
    assert result.hits[0].provider_provenance == ("searxng", "bing")
    assert result.hits[0].provider_rank == 1
    assert not hasattr(result.hits[0], "evidence")


def test_unsupported_legacy_constraints_do_not_silently_change_the_query():
    class Legacy:
        def search_exact(self, *args, **kwargs):
            pytest.fail("Unsupported contract must not silently fall through")

    result = LegacyDiscoveryAdapter(Legacy()).search(DiscoveryRequest("query", "release", 8, 10.0, live=True))
    assert result.status == "unavailable"
    assert result.reason == "unsupported_request_constraints"


@pytest.mark.parametrize("limit,deadline", [(0, 10.0), (25, 10.0), (8, float("inf"))])
def test_discovery_request_enforces_bounds(limit, deadline):
    with pytest.raises(ValueError):
        DiscoveryRequest("query", "general", limit, deadline)


def test_registry_is_operation_specific_and_never_qualifies_from_documentation():
    entries = platform_capability_registry()
    assert not any(row.qualification == "qualified" for row in entries)
    by_key = {(row.platform, row.operation): row for row in entries}
    assert by_key["bilibili", "search"].auth_level == "anonymous"
    assert by_key["bilibili", "subtitles"].auth_level == "optional_auth"
    assert by_key["xhs", "search"].qualification == "unavailable"


def test_sidecar_results_bind_request_and_never_grant_factual_authority():
    request = PlatformRequest("request-new", "bilibili", "search", "Python", 3, 100.0)
    hit = PlatformHit("bilibili", "video-1", "https://www.bilibili.com/video/video-1", "title", "preview", "video_metadata")
    valid = PlatformBatch("request-new", "bilibili", (hit,), "ok")
    assert validate_platform_batch(request, valid) is valid
    assert hit.epistemic_kind == "community_observation"
    with pytest.raises(ValueError, match="binding"):
        validate_platform_batch(request, PlatformBatch("request-old", "bilibili", (hit,), "ok"))
    with pytest.raises(ValueError, match="status"):
        validate_platform_batch(request, PlatformBatch("request-new", "bilibili", (), "ok"))
    with pytest.raises(ValueError, match="status"):
        validate_platform_batch(request, PlatformBatch("request-new", "bilibili", (), "unknown"))
    with pytest.raises(ValueError):
        PlatformHit("bilibili", "video-1", "http://127.0.0.1/private", "title", "preview", "video_metadata")


def test_auth_required_is_distinct_from_an_empty_success():
    request = PlatformRequest("request-new", "xhs", "search", "Python", 3, 100.0)
    batch = PlatformBatch("request-new", "xhs", (), "auth_required", "operator_session_required")
    assert validate_platform_batch(request, batch).status == "auth_required"
    with pytest.raises(TypeError):
        PlatformRequest("id", "xhs", "search", "q", 3, 10.0, cookies="credential")
