"""Deterministic tests for the §37A discovery join and rate summary."""

from __future__ import annotations

from tools.run_support_formation_audit import (
    _search_discovery_projection,
    summarize_discovery_rates,
)


def _case() -> dict:
    return {
        "case_id": "case-x",
        "gate": {"status": "block"},
        "metrics": {
            "search_discovery": {
                "queries": [
                    {
                        "slot_index": 1,
                        "query_sha256": "a" * 64,
                        "query_excerpt": "docker hub pull limits docs",
                        "page_intent": {"kind": "limit_policy"},
                        "generated_query_variants": [
                            "docker hub pull limits",
                            "docker hub pull limits docs",
                        ],
                        "variant_matches": [0, 1],
                        "hint_terms": ["docker", "hub", "limits"],
                        "results": [
                            {
                                "result_rank": 1,
                                "url": "https://docs.docker.com/docker-hub/usage/pulls/",
                                "title": "Pull limits",
                                "snippet": "rate limits",
                                "authority_class": "unknown",
                                "lexical_targeting_score": {"candidate_title_match": 1},
                                "selection_reason": "missing_fact_title_match",
                            },
                            {
                                "result_rank": 2,
                                "url": "https://www.runoob.com/docker/docker-tutorial.html",
                                "title": "Tutorial",
                                "snippet": "learn docker",
                                "authority_class": "tutorial",
                                "lexical_targeting_score": {"candidate_title_match": 0},
                                "selection_reason": "fallback_order",
                            },
                        ],
                    }
                ]
            },
            "deeper_targeting": {
                "recent": [
                    {
                        "selected_candidate_url": "https://docs.docker.com/docker-hub/usage/pulls/",
                    }
                ]
            },
        },
        "sources": [
            {
                "url": "https://docs.docker.com/docker-hub/usage/pulls/",
                "read_status": "read",
            }
        ],
        "brief": {
            "eligible_evidence": [
                {
                    "url": "https://docs.docker.com/docker-hub/usage/pulls/",
                    "relation": "lead",
                    "caveats": ["does not state the numeric limits"],
                }
            ]
        },
    }


def test_projection_joins_results_with_selection_and_read_truth() -> None:
    projection = _search_discovery_projection(_case())

    assert projection["query_count"] == 1
    rows = projection["queries"][0]["results"]
    first, second = rows
    assert first["selected_for_harvest"] is True
    assert first["selected_for_read"] is True
    assert first["read_status"] == "read"
    assert first["final_relation"] == "lead"
    assert first["final_caveat"].startswith("does not state")
    assert second["selected_for_harvest"] is False
    assert second["selected_for_read"] is False
    # Human fields are never auto-filled.
    assert all(row["human_candidate_classification"] == "" for row in rows)
    assert projection["human_target_fact_present_after_read"] == ""
    assert projection["issued_variant_coverage"]["generated_total"] == 2


def test_rates_are_pending_until_human_labels_exist() -> None:
    projection = _search_discovery_projection(_case())

    rates = summarize_discovery_rates([projection])

    assert rates["status"] == "pending_human_classification"
    assert rates["audited_cases"] == 0
    assert rates["target_fact_candidate_rate"] is None
    assert rates["target_fact_selected_rate"] is None


def test_rates_compute_from_human_labels() -> None:
    projection = _search_discovery_projection(_case())
    rows = projection["queries"][0]["results"]
    rows[0]["human_candidate_classification"] = "likely_target"
    projection["human_target_fact_present_after_read"] = "yes"

    rates = summarize_discovery_rates([projection])

    assert rates["status"] == "computed_from_human_labels"
    assert rates["audited_cases"] == 1
    assert rates["target_fact_candidate_rate"] == 1.0
    assert rates["target_fact_selected_rate"] == 1.0
    assert rates["target_fact_present_after_read"] == 1.0


def test_likely_target_that_was_not_selected_lowers_selected_rate() -> None:
    projection = _search_discovery_projection(_case())
    rows = projection["queries"][0]["results"]
    rows[1]["human_candidate_classification"] = "likely_target"  # not read

    rates = summarize_discovery_rates([projection])

    assert rates["target_fact_candidate_rate"] == 1.0
    assert rates["target_fact_selected_rate"] == 0.0


def test_projection_tolerates_missing_observability() -> None:
    projection = _search_discovery_projection({"case_id": "case-y"})

    assert projection["query_count"] == 0
    assert projection["queries"] == []
    assert summarize_discovery_rates([projection])["status"] == (
        "pending_human_classification"
    )
