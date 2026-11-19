"""Run-level coverage projection contracts, independent of model and readers."""

from src.application.research_runtime_read_coverage import (
    ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY,
    merge_covered_clusters,
)


def test_preserves_persisted_history_and_binds_shared_read_extractions() -> None:
    context = {
        ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY: {
            "claim_a": ["previous", "previous"],
            "claim_b": ("older",),
        },
        "unrelated": {"keep": True},
    }
    sources = [
        {
            "read_status": "read",
            "assessment": {
                "claim_id": "claim_a",
                "source_cluster_id": "shared",
            },
            "extractions": {"claim_b": {}, 99: {}},
        }
    ]

    coverage = merge_covered_clusters(context, sources)

    assert coverage == {
        "claim_a": {"previous", "shared"},
        "claim_b": {"older", "shared"},
    }
    assert context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY] == {
        "claim_a": ["previous", "shared"],
        "claim_b": ["older", "shared"],
    }
    assert context["unrelated"] == {"keep": True}


def test_ignores_failed_reads_missing_clusters_and_malformed_old_entries() -> None:
    context = {
        ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY: {
            "broken": "not-a-cluster-list",
            "claim_a": {"retained"},
        }
    }
    sources = [
        {
            "read_status": "failed",
            "assessment": {"claim_id": "claim_a", "source_cluster_id": "failure"},
        },
        {"read_status": "read", "assessment": "old-shape"},
        {"read_status": "read", "assessment": {"claim_id": "claim_a"}},
        {
            "read_status": "read",
            "assessment": {"source_cluster_id": "unowned"},
            "extractions": {12: {}},
        },
    ]

    coverage = merge_covered_clusters(context, sources)

    assert coverage == {"claim_a": {"retained"}}
    assert context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY] == {
        "claim_a": ["retained"]
    }


def test_resume_without_new_reads_keeps_prior_coverage_idempotently() -> None:
    context = {ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY: {"claim_b": ["cluster-y"]}}

    first = merge_covered_clusters(context, [])
    second = merge_covered_clusters(context, [])

    assert first == second == {"claim_b": {"cluster-y"}}
    assert context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY] == {
        "claim_b": ["cluster-y"]
    }
