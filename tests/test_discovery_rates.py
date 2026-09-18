"""§37A.1 accounting: three states, URL dedup, case-level rates, saturation."""

from __future__ import annotations

from tools.run_support_formation_audit import (
    _search_discovery_projection,
    summarize_discovery_rates,
)
from src.web.research.discovery_observability import (
    STATE_FALSE,
    STATE_TRUE,
    STATE_UNOBSERVED,
    dedupe_candidates,
    saturation_metrics,
)

DOCS = "https://docs.docker.com/docker-hub/usage/pulls/"
TUTORIAL = "https://www.runoob.com/docker/docker-tutorial.html"


def _queries(urls_per_query: list[list[str]]) -> list[dict]:
    return [
        {
            "slot_index": index + 1,
            "query_sha256": f"{index:064d}",
            "query_excerpt": f"query {index}",
            "page_intent": {"kind": "limit_policy"},
            "generated_query_variants": [f"variant {index}"],
            "variant_matches": [0],
            "hint_terms": ["docker", "limits"],
            "results": [
                {
                    "result_rank": rank + 1,
                    "url": url,
                    "title": f"title {rank}",
                    "snippet": "snip",
                    "authority_class": "unknown",
                    "lexical_targeting_score": {"candidate_title_match": 1},
                    "selection_reason": "missing_fact_title_match",
                }
                for rank, url in enumerate(urls)
            ],
        }
    for index, urls in enumerate(urls_per_query)
    ]


def _case(*, harvested: list[str] | None = None, reads: list[str] | None = None,
          lead_added: int = 0, queries: list[dict] | None = None) -> dict:
    reads = reads or []
    return {
        "case_id": "case-x",
        "metrics": {
            "search_discovery": {
                "queries": queries
                if queries is not None
                else _queries([[DOCS, TUTORIAL], [DOCS, TUTORIAL]])
            },
            "deeper_targeting": {
                "recent": [
                    {"selected_candidate_url": url} for url in (harvested or [])
                ]
            },
            "lead_discovery": {"evidence_lead_candidate_added": lead_added},
        },
        "sources": [
            {"url": url, "read_status": "read"} for url in reads
        ],
        "brief": {
            "eligible_evidence": [
                {"url": DOCS, "relation": "lead", "caveats": ["does not state limits"]}
            ]
        },
    }


def test_harvest_is_unobserved_without_a_harvest_attempt() -> None:
    projection = _search_discovery_projection(_case(reads=[DOCS]))

    assert projection["harvest_probe"] == "no_harvest_attempt"
    candidates = {item["canonical_url"]: item for item in projection["unique_candidates"]}
    assert candidates[DOCS]["selected_for_harvest"] == STATE_UNOBSERVED
    # Read, by contrast, *is* observable per case: not read means false.
    assert candidates[DOCS]["selected_for_read"] == STATE_TRUE
    assert candidates[TUTORIAL]["selected_for_read"] == STATE_FALSE


def test_harvest_becomes_false_only_when_a_probe_ran() -> None:
    projection = _search_discovery_projection(
        _case(harvested=[DOCS], reads=[DOCS])
    )

    assert projection["harvest_probe"] == "observed"
    candidates = {item["canonical_url"]: item for item in projection["unique_candidates"]}
    assert candidates[DOCS]["selected_for_harvest"] == STATE_TRUE
    assert candidates[TUTORIAL]["selected_for_harvest"] == STATE_FALSE


def test_unique_candidates_dedupe_repeated_recall() -> None:
    queries = _queries([[DOCS, TUTORIAL]] * 5)
    projection = _search_discovery_projection(_case(queries=queries, reads=[DOCS]))

    assert projection["occurrence_count"] == 10
    assert len(projection["unique_candidates"]) == 2
    docs = next(
        item for item in projection["unique_candidates"] if item["canonical_url"] == DOCS
    )
    assert docs["occurrence_count"] == 5
    assert len(docs["occurrence_indices"]) == 5


def test_saturation_metrics_quantify_repetition() -> None:
    queries = _queries([[DOCS, TUTORIAL], [DOCS, TUTORIAL], [DOCS]])

    metrics = saturation_metrics(queries)

    assert metrics["query_count"] == 3
    assert metrics["unique_urls_per_case"] == 2
    assert metrics["new_url_gain_after_q1"] == 0
    assert metrics["pairwise_result_set_overlap"] == [1.0, 0.5]


def test_dedupe_candidates_returns_occurrence_map() -> None:
    """Tracking params and fragments collapse; unknown params are preserved."""

    rows = [
        {"url": DOCS, "result_rank": 1},
        {"url": DOCS + "?utm_source=x&utm_medium=y", "result_rank": 2},
        {"url": DOCS + "#section", "result_rank": 3},
        {"url": DOCS + "?page=2", "result_rank": 4},
    ]

    unique, occurrences = dedupe_candidates(rows)

    # Dedup is canonical, not fuzzy: a real page parameter stays its own row.
    assert len(unique) == 2
    assert occurrences[DOCS] == [1, 2, 3]
    assert occurrences[DOCS + "?page=2"] == [4]


def test_rates_are_pending_until_candidates_are_classified() -> None:
    projection = _search_discovery_projection(_case(reads=[DOCS]))

    rates = summarize_discovery_rates([projection])

    assert rates["status"] == "pending_human_classification"
    assert rates["target_fact_candidate_rate"] is None
    assert rates["target_fact_harvest_rate"] == "unobserved"


def test_case_level_rates_do_not_weight_repeated_occurrences() -> None:
    projection = _search_discovery_projection(
        _case(queries=_queries([[DOCS, TUTORIAL]] * 4), reads=[DOCS])
    )
    for candidate in projection["unique_candidates"]:
        if candidate["canonical_url"] == DOCS:
            candidate["human_candidate_classification"] = "likely_target"
            candidate["human_target_fact_present_after_read"] = "true"
        else:
            candidate["human_candidate_classification"] = "irrelevant"

    rates = summarize_discovery_rates([projection])

    assert rates["classified_cases"] == 1
    assert rates["target_fact_candidate_rate"] == 1.0
    assert rates["target_fact_selected_rate"] == 1.0
    assert rates["target_fact_read_rate"] == 1.0
    assert rates["target_fact_present_after_read"] == 1.0


def test_presence_on_an_unread_candidate_is_an_accounting_violation() -> None:
    projection = _search_discovery_projection(_case(reads=[DOCS]))
    for candidate in projection["unique_candidates"]:
        if candidate["canonical_url"] == TUTORIAL:
            candidate["human_candidate_classification"] = "near_hit"
            candidate["human_target_fact_present_after_read"] = "false"

    rates = summarize_discovery_rates([projection])

    assert rates["accounting_violations"]
    assert rates["accounting_violations"][0]["canonical_url"] == TUTORIAL


def test_missing_observability_is_empty_not_false() -> None:
    projection = _search_discovery_projection({"case_id": "case-y"})

    assert projection["unique_candidates"] == []
    assert projection["harvest_probe"] == "no_harvest_attempt"
    assert projection["saturation"]["unique_urls_per_case"] == 0
