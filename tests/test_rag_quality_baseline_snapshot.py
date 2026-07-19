from __future__ import annotations

import json
from pathlib import Path

from tools.run_rag_quality_baseline import run_baseline


FIXTURE_DIR = Path("tests/fixtures/rag_eval")
SNAPSHOT_PATH = FIXTURE_DIR / "baseline_v4_summary.json"
SOURCE_COVERAGE_CONTRACT_PATH = FIXTURE_DIR / "source_coverage_v2_contract.json"
PROFILE_METRICS = (
    "source_hit_rate",
    "mean_precision_at_k",
    "mean_recall_at_k",
    "mean_reciprocal_rank",
    "mean_ndcg_at_k",
    "forbidden_source_leakage_rate",
    "unanswerable_nonempty_rate",
)
SUFFICIENCY_METRICS = (
    "total_cases",
    "answerable_cases",
    "unanswerable_cases",
    "answerability_accuracy",
    "answerable_supported_rate",
    "unanswerable_block_rate",
    "supported_rate",
    "uncertain_rate",
    "insufficient_rate",
    "status_counts",
)
ANSWER_METRICS = (
    "answerability_accuracy",
    "mean_citation_precision",
    "mean_citation_recall",
    "mean_claim_coverage",
    "mean_claim_support_rate",
    "mean_groundedness",
    "mean_source_diversity",
    "stale_revision_leakage_rate",
)


def test_rag_k1_baseline_changes_require_an_explicit_snapshot_update():
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    actual = run_baseline(FIXTURE_DIR)

    assert actual["schema_version"] == expected["schema_version"]
    assert actual["baseline_kind"] == expected["baseline_kind"]
    assert actual["gating"] == expected["gating"] == "record_only"
    assert {
        key: actual["corpus"][key]
        for key in (
            "fingerprint_sha256",
            "documents",
            "retrieval_cases",
            "answer_cases",
            "evidence_status_counts",
        )
    } == expected["corpus"]

    for profile_name, expected_metrics in expected["retrieval_profiles"].items():
        actual_profile = actual["retrieval_profiles"][profile_name]
        assert {
            metric: actual_profile[metric] for metric in PROFILE_METRICS
        } == expected_metrics

    actual_hybrid_scenarios = actual["retrieval_profiles"]["hybrid"]["scenario_summaries"]
    for scenario, expected_metrics in expected["hybrid_scenarios"].items():
        assert {
            metric: actual_hybrid_scenarios[scenario][metric]
            for metric in expected_metrics
        } == expected_metrics

    actual_adaptive = actual["adaptive_source_coverage"]
    assert {
        metric: actual_adaptive[metric] for metric in PROFILE_METRICS
    } == expected["adaptive_source_coverage"]
    actual_adaptive_multi = actual_adaptive["scenario_summaries"]["multi_source"]
    assert {
        metric: actual_adaptive_multi[metric]
        for metric in expected["adaptive_multi_source"]
    } == expected["adaptive_multi_source"]

    assert {
        metric: actual["evidence_sufficiency"][metric]
        for metric in SUFFICIENCY_METRICS
    } == expected["evidence_sufficiency"]

    assert {
        metric: actual["answer_quality"][metric] for metric in ANSWER_METRICS
    } == expected["answer_quality"]


def test_k1d_source_coverage_quality_contract():
    contract = json.loads(SOURCE_COVERAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    actual = run_baseline(FIXTURE_DIR)
    requirements = contract["requirements"]
    adaptive = actual["adaptive_source_coverage"]
    multi_source = adaptive["scenario_summaries"]["multi_source"]
    sufficiency = actual["evidence_sufficiency"]

    assert multi_source["mean_recall_at_k"] >= requirements["multi_source_min_recall_at_k"]
    assert multi_source["mean_precision_at_k"] >= requirements["multi_source_min_precision_at_k"]
    if requirements["require_overall_recall_non_regression_vs_raw_hybrid"]:
        assert adaptive["mean_recall_at_k"] >= actual["retrieval_profiles"]["hybrid"][
            "mean_recall_at_k"
        ]
    assert sufficiency["answerable_supported_rate"] >= requirements[
        "min_answerable_supported_rate"
    ]
    assert sufficiency["unanswerable_block_rate"] >= requirements[
        "min_unanswerable_block_rate"
    ]
    assert adaptive["forbidden_source_leakage_rate"] <= requirements[
        "max_forbidden_source_leakage_rate"
    ]
