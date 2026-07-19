from __future__ import annotations

import json
from pathlib import Path

from tools.run_rag_quality_baseline import run_baseline


FIXTURE_DIR = Path("tests/fixtures/rag_eval")
SNAPSHOT_PATH = FIXTURE_DIR / "baseline_v1_summary.json"
PROFILE_METRICS = (
    "source_hit_rate",
    "mean_precision_at_k",
    "mean_recall_at_k",
    "mean_reciprocal_rank",
    "mean_ndcg_at_k",
    "forbidden_source_leakage_rate",
    "unanswerable_nonempty_rate",
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
        for key in ("fingerprint_sha256", "documents", "retrieval_cases", "answer_cases")
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

    assert {
        metric: actual["answer_quality"][metric] for metric in ANSWER_METRICS
    } == expected["answer_quality"]
