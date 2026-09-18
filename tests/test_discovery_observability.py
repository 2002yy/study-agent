"""§37A search-discovery observability: bounded, deterministic, non-semantic."""

from __future__ import annotations

from src.web.research.discovery_observability import (
    DEFAULT_MAX_QUERIES,
    DEFAULT_TOP_K,
    SCHEMA_VERSION,
    issued_variant_coverage,
    record_search_call,
    variant_matches,
)
from src.web.research.page_intent import infer_page_intent

METRICS_KEY = "active_research_metrics"


def _record(
    context: dict,
    *,
    slot_index: int = 1,
    query: str = "docker hub pull rate limits docs",
    claim_id: str = "claim-1",
    intent=None,
    variants=("docker hub pull rate limits", "docker hub pull limits docs"),
    hint_terms=("docker", "hub", "limits"),
    results=(
        {
            "url": "https://docs.docker.com/docker-hub/usage/pulls/",
            "title": "Pull rate limits",
            "snippet": "rate limits for unauthenticated users",
            "provider": "bing_rss",
            "providers": ["bing_rss"],
        },
        {
            "url": "https://www.runoob.com/docker/docker-tutorial.html",
            "title": "Docker tutorial",
            "snippet": "learn docker step by step",
            "provider": "searxng",
            "providers": ["searxng"],
        },
    ),
    top_k: int = 5,
) -> None:
    record_search_call(
        context,
        metrics_key=METRICS_KEY,
        slot_index=slot_index,
        query=query,
        claim_id=claim_id,
        intent=intent if intent is not None else infer_page_intent(claim_terms=("rate", "limits")),
        variants=variants,
        hint_terms=hint_terms,
        results=results,
        top_k=top_k,
    )


def test_records_query_results_and_mechanical_signals() -> None:
    context: dict = {}

    _record(context)

    state = context[METRICS_KEY]["search_discovery"]
    assert state["schema_version"] == SCHEMA_VERSION
    assert state["outcome"] == "observability_only"
    assert len(state["queries"]) == 1
    item = state["queries"][0]
    assert item["slot_index"] == 1
    assert item["query_excerpt"].startswith("docker hub pull")
    assert len(item["query_sha256"]) == 64
    assert item["generated_query_variants"] == [
        "docker hub pull rate limits",
        "docker hub pull limits docs",
    ]
    assert item["hint_terms"] == ["docker", "hub", "limits"]
    assert item["page_intent"]["kind"] == "limit_policy"
    assert item["result_count"] == 2

    first = item["results"][0]
    assert first["result_rank"] == 1
    assert first["url"].startswith("https://docs.docker.com/")
    assert first["authority_class"]
    assert first["lexical_targeting_score"]["candidate_title_match"] >= 1
    assert first["selection_reason"]
    # No semantic verdict is ever recorded by the tool itself.
    assert first["human_candidate_classification"] == ""
    assert first["selected_for_harvest"] is False
    assert first["selected_for_read"] is False
    assert first["read_status"] == ""
    assert first["final_relation"] == ""
    assert first["final_caveat"] == ""


def test_title_and_snippet_are_strictly_bounded() -> None:
    context: dict = {}

    _record(
        context,
        results=[
            {
                "url": "https://example.test/x",
                "title": "T" * 500,
                "snippet": "S" * 900,
            }
        ],
    )

    row = context[METRICS_KEY]["search_discovery"]["queries"][0]["results"][0]
    assert len(row["title"]) <= 200
    assert len(row["snippet"]) <= 240
    assert row["url"].startswith("https://example.test/x")


def test_top_k_and_query_cap_are_enforced() -> None:
    context: dict = {}
    many_results = [
        {"url": f"https://example.test/{index}", "title": f"t{index}", "snippet": "s"}
        for index in range(20)
    ]

    _record(context, results=many_results, top_k=3)
    for slot in range(2, DEFAULT_MAX_QUERIES + 5):
        _record(context, slot_index=slot, results=many_results, top_k=3)

    queries = context[METRICS_KEY]["search_discovery"]["queries"]
    assert len(queries) <= DEFAULT_MAX_QUERIES
    assert all(len(item["results"]) <= 3 for item in queries)
    assert DEFAULT_TOP_K == 5


def test_recording_is_deterministic_for_identical_inputs() -> None:
    first: dict = {}
    second: dict = {}

    _record(first, slot_index=3)
    _record(second, slot_index=3)

    assert first == second


def test_odd_payloads_are_tolerated() -> None:
    context: dict = {}

    _record(context, results=[{"url": ""}, "not-a-mapping", {"no_url": True}])

    item = context[METRICS_KEY]["search_discovery"]["queries"][0]
    assert item["result_count"] == 0
    assert item["results"] == []


def test_variant_matches_report_only_term_overlap() -> None:
    variants = ("docker hub pull limits", "postgresql supported versions")

    assert variant_matches("docker hub pull limits docs", variants) == [0]
    assert variant_matches("completely different query", variants) == []
    assert variant_matches("postgresql supported versions policy", variants) == [1]


def test_issued_variant_coverage_is_mechanical() -> None:
    context: dict = {}
    _record(context, slot_index=1)
    _record(
        context,
        slot_index=2,
        query="docker hub pull limits docs",
        variants=("docker hub pull limits docs", "unused second variant"),
    )

    coverage = issued_variant_coverage(
        context[METRICS_KEY]["search_discovery"]["queries"]
    )

    assert coverage["generated_total"] == 4
    assert coverage["matched_total"] >= 2
    assert [entry["slot_index"] for entry in coverage["queries"]] == [1, 2]
    assert "mechanical term overlap" in coverage["note"]


def test_missing_metrics_key_creates_a_bounded_state() -> None:
    context: dict = {}

    _record(context, results=())

    state = context[METRICS_KEY]["search_discovery"]
    assert state["queries"][0]["result_count"] == 0
