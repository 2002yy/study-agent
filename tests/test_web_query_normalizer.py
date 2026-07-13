from __future__ import annotations

from datetime import datetime, timezone

from src.web.query_normalizer import normalize_web_query
from src.web.tool_gateway import GeneralWebGateway


def test_gpt56sol_is_normalized_without_claiming_product_existence():
    normalized = normalize_web_query(
        "联网看看gpt5.6sol",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert normalized.canonical_query == "GPT-5.6 Sol"
    assert normalized.query_variants[0] == "GPT-5.6 Sol"
    assert "gpt5.6sol" in normalized.query_variants
    assert "联网看看gpt5.6sol" in normalized.query_variants
    assert "gpt5.6sol" in normalized.entity_aliases
    assert normalized.search_directive_removed is True
    assert normalized.as_of_date == "2026-07-13"


def test_english_search_directive_is_removed_from_focused_query():
    normalized = normalize_web_query(
        "Please search the web for GPT5.6Sol",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert normalized.canonical_query == "GPT-5.6 Sol"
    assert normalized.search_directive_removed is True
    assert normalized.raw_query == "Please search the web for GPT5.6Sol"


def test_compact_model_pattern_does_not_partially_rewrite_larger_words():
    normalized = normalize_web_query(
        "gpt5.6solution design",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert normalized.canonical_query == "gpt5.6solution design"
    assert normalized.entity_aliases == ()


def test_latest_query_records_freshness_window_and_current_month_variant():
    normalized = normalize_web_query(
        "GPT5.6Sol 最新进展",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert normalized.freshness_requested is True
    assert normalized.freshness_days == 30
    assert any("July 2026" in variant for variant in normalized.query_variants)


def test_explicit_year_does_not_inject_current_month():
    normalized = normalize_web_query(
        "GPT5.6Sol 2025 发布",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert all("July 2026" not in variant for variant in normalized.query_variants)


def test_detailed_search_reports_empty_without_inferring_nonexistence(monkeypatch):
    gateway = GeneralWebGateway()
    attempted: list[str] = []

    def empty_search(query: str, limit: int):
        attempted.append(query)
        return []

    monkeypatch.setattr(gateway, "_search_single", empty_search)
    monkeypatch.setattr("src.web.tool_gateway.searxng_enabled", lambda: True)

    payload = gateway.search_detailed(
        "gpt5.6sol",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert payload["status"] == "empty"
    assert payload["reason"] == "providers_returned_no_results"
    assert payload["results"] == []
    assert payload["attempted_queries"] == attempted
    assert attempted[0] == "GPT-5.6 Sol"
    assert "nonexistent" not in str(payload).lower()


def test_detailed_search_prefers_canonical_variant_and_stops_after_results(monkeypatch):
    gateway = GeneralWebGateway()
    attempted: list[str] = []

    def search(query: str, limit: int):
        attempted.append(query)
        if query == "GPT-5.6 Sol":
            return [
                {
                    "title": "Official model page",
                    "url": "https://example.test/model",
                    "snippet": "model details",
                    "source": "test",
                    "published_at": "2026-07-13",
                }
            ]
        return []

    monkeypatch.setattr(gateway, "_search_single", search)

    payload = gateway.search_detailed(
        "gpt5.6sol",
        now=datetime(2026, 7, 13, 4, 0, tzinfo=timezone.utc),
    )

    assert payload["status"] == "ok"
    assert payload["reason"] == "results_found"
    assert attempted == ["GPT-5.6 Sol"]
    assert payload["results"][0]["title"] == "Official model page"
