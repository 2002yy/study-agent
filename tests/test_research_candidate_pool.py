from __future__ import annotations

from typing import Any

import pytest

from src.web.research.candidate_pool import (
    CandidatePoolCancelled,
    CandidatePoolProgress,
    execute_candidate_pool_batch,
)
from src.web.research.gap_planner import (
    GapQueryBatch,
    GapSearchIntent,
    PlannedGapQuery,
)


def _batch(count: int = 4) -> GapQueryBatch:
    intents = (
        GapSearchIntent.DISCOVERY,
        GapSearchIntent.PRIMARY,
        GapSearchIntent.PROVENANCE,
        GapSearchIntent.VERIFICATION,
    )
    queries = tuple(
        PlannedGapQuery(
            id=f"gap-1:{intent.value}",
            gap_id="gap-1",
            claim_id="claim-1",
            intent=intent,
            query=f"focused query {intent.value}",
            desired_source_role="primary",
        )
        for intent in intents[:count]
    )
    return GapQueryBatch(
        gap_id="gap-1",
        claim_id="claim-1",
        focused_surface="focused query",
        queries=queries,
    )


def test_nonempty_first_query_never_stops_remaining_batch() -> None:
    calls: list[str] = []
    checkpoints: list[CandidatePoolProgress] = []

    def search(query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        calls.append(query)
        if len(calls) == 1:
            return {
                "status": "ok",
                "reason": "results_found",
                "providers_attempted": ["bing_rss"],
                "results": [
                    {
                        "title": "Current - dictionary definition",
                        "url": "https://dictionary.example/current",
                        "source": "Bing RSS",
                    }
                ],
            }
        if len(calls) == 2:
            return {
                "status": "ok",
                "reason": "results_found",
                "providers_attempted": ["searxng"],
                "results": [
                    {
                        "title": "Official API rate limit documentation",
                        "url": "https://docs.example/api/rate-limit",
                        "source": "SearXNG",
                    }
                ],
            }
        return {
            "status": "empty",
            "reason": "providers_returned_no_results",
            "providers_attempted": ["searxng", "bing_rss"],
            "results": [],
        }

    result = execute_candidate_pool_batch(
        _batch(),
        search_exact=search,
        checkpoint=checkpoints.append,
    )

    assert len(calls) == 4
    assert len(result.outcomes) == 4
    assert len(checkpoints) == 4
    assert [item.completed_queries for item in checkpoints] == [1, 2, 3, 4]
    assert {item.title for item in result.candidates} == {
        "Current - dictionary definition",
        "Official API rate limit documentation",
    }
    assert result.status == "completed"


def test_pool_canonicalizes_dedupes_and_preserves_discovery_provenance() -> None:
    calls = 0

    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        nonlocal calls
        calls += 1
        suffix = "?utm_source=one" if calls == 1 else "?utm_source=two"
        return {
            "status": "ok",
            "providers_attempted": ["searxng" if calls == 1 else "bing_rss"],
            "results": [
                {
                    "title": (
                        "Official result"
                        if calls == 1
                        else "Official result with detail"
                    ),
                    "url": f"https://docs.example/item{suffix}",
                    "snippet": "short" if calls == 1 else "a longer useful snippet",
                    "source": "provider-a" if calls == 1 else "provider-b",
                }
            ],
        }

    result = execute_candidate_pool_batch(_batch(2), search_exact=search)
    assert len(result.candidates) == 1
    item = result.candidates[0]
    assert item.canonical_url == "https://docs.example/item"
    assert len(item.query_ids) == 2
    assert item.intents == (GapSearchIntent.DISCOVERY, GapSearchIntent.PRIMARY)
    assert {"searxng", "bing_rss"} <= set(item.providers)
    assert item.title == "Official result with detail"
    assert item.snippet == "a longer useful snippet"


def test_result_provider_is_precise_while_outcome_preserves_all_attempts() -> None:
    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        return {
            "status": "ok",
            "providers_attempted": ["searxng", "bing_rss", "duckduckgo_html"],
            "provider_errors": ["searxng:timeout"],
            "results": [
                {
                    "title": "Result returned by fallback",
                    "url": "https://example.test/fallback",
                    "provider": "bing_rss",
                    "source": "Example Publisher",
                }
            ],
        }

    result = execute_candidate_pool_batch(_batch(2), search_exact=search)
    assert result.outcomes[0].providers_attempted == (
        "searxng",
        "bing_rss",
        "duckduckgo_html",
    )
    assert result.outcomes[0].provider_errors == ("searxng:timeout",)
    assert result.candidates[0].providers == ("bing_rss",)
    assert result.candidates[0].source == "Example Publisher"


def test_result_provider_list_beats_payload_attempted_providers() -> None:
    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        return {
            "status": "ok",
            "providers_attempted": ["searxng", "bing_rss", "duckduckgo_html"],
            "results": [
                {
                    "title": "Shared result",
                    "url": "https://example.test/shared",
                    "providers": ["bing_rss", "searxng", "bing_rss"],
                }
            ],
        }

    result = execute_candidate_pool_batch(_batch(1), search_exact=search)
    assert result.candidates[0].providers == ("bing_rss", "searxng")


def test_missing_or_malformed_result_provenance_uses_legacy_payload_fallback() -> None:
    calls = 0

    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        nonlocal calls
        calls += 1
        return {
            "status": "ok",
            "providers_attempted": ["searxng" if calls == 1 else "bing_rss"],
            "results": [
                {
                    "title": "Legacy result",
                    "url": "https://example.test/legacy",
                    "providers": "not-a-list" if calls == 1 else [],
                    "provider": "",
                }
            ],
        }

    result = execute_candidate_pool_batch(_batch(2), search_exact=search)
    assert len(result.candidates) == 1
    assert result.candidates[0].providers == ("searxng", "bing_rss")


def test_duplicate_candidate_unions_only_providers_that_returned_it() -> None:
    calls = 0

    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        nonlocal calls
        calls += 1
        provider = "bing_rss" if calls == 1 else "searxng"
        return {
            "status": "ok",
            "providers_attempted": ["searxng", "bing_rss", "duckduckgo_html"],
            "results": [
                {
                    "title": "Same result",
                    "url": f"https://example.test/same?utm_source={calls}",
                    "provider": provider,
                }
            ],
        }

    result = execute_candidate_pool_batch(_batch(2), search_exact=search)
    assert len(result.candidates) == 1
    assert result.candidates[0].providers == ("bing_rss", "searxng")
    assert "duckduckgo_html" not in result.candidates[0].providers


def test_provider_failure_empty_and_success_remain_distinguishable() -> None:
    calls = 0

    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("provider timeout")
        if calls == 2:
            return {
                "status": "empty",
                "reason": "providers_returned_no_results",
                "providers_attempted": ["searxng"],
                "results": [],
            }
        return {
            "status": "ok",
            "reason": "results_found",
            "providers_attempted": ["bing_rss"],
            "results": [
                {
                    "title": "Result",
                    "url": "https://example.test/result",
                }
            ],
        }

    result = execute_candidate_pool_batch(_batch(3), search_exact=search)
    assert [item.status for item in result.outcomes] == ["unavailable", "empty", "ok"]
    assert result.outcomes[0].provider_errors == ("search_exception:TimeoutError",)
    assert result.status == "completed"


def test_cancellation_is_checked_after_each_query_before_checkpoint() -> None:
    search_calls = 0
    checkpoints: list[CandidatePoolProgress] = []

    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        nonlocal search_calls
        search_calls += 1
        return {"status": "empty", "results": []}

    with pytest.raises(CandidatePoolCancelled):
        execute_candidate_pool_batch(
            _batch(),
            search_exact=search,
            should_cancel=lambda: search_calls >= 1,
            checkpoint=checkpoints.append,
        )

    assert search_calls == 1
    assert checkpoints == []


def test_unsafe_or_titleless_results_are_cheap_filtered() -> None:
    def search(_query: str, *, max_results: int) -> dict[str, Any]:
        assert max_results == 5
        return {
            "status": "ok",
            "results": [
                {"title": "Unsafe", "url": "file:///etc/passwd"},
                {"title": "", "url": "https://example.test/no-title"},
            ],
        }

    result = execute_candidate_pool_batch(_batch(2), search_exact=search)
    assert result.status == "empty"
    assert result.candidates == ()


def test_a_section_fragment_is_kept_for_the_read_not_the_identity() -> None:
    from src.web.research.candidate_pool import merge_candidate_pool

    query = PlannedGapQuery(
        id="gap-1:primary",
        gap_id="gap-1",
        claim_id="claim-1",
        intent=GapSearchIntent.PRIMARY,
        query="guide install",
        desired_source_role="primary",
    )
    items = merge_candidate_pool([
        (
            query,
            (
                {"title": "Guide install", "url": "https://example.com/guide#install"},
                {"title": "Guide install (dup)", "url": "https://example.com/guide"},
            ),
            ("searxng",),
        )
    ])

    assert len(items) == 1
    assert items[0].canonical_url == "https://example.com/guide"
    assert items[0].url == "https://example.com/guide#install"
