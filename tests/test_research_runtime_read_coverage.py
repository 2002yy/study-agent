"""Run-level coverage projection contracts, independent of model and readers."""

from dataclasses import fields
from typing import cast

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_coverage import (
    ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY,
    merge_covered_clusters,
    project_covered_clusters,
)
from src.application.research_runtime_read_coverage_context import (
    ActiveReadCoverageContext,
)
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.web.research.contracts import ResearchState


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


def test_projection_does_not_mutate_persisted_history_or_sources() -> None:
    previous = {"claim_a": ["old", "old"], "invalid": "legacy"}
    sources = [
        {
            "read_status": "read",
            "assessment": {"claim_id": "claim_a", "source_cluster_id": "new"},
            "extractions": {"claim_b": {}},
        }
    ]
    expected = {"claim_a": {"old", "new"}, "claim_b": {"new"}}

    assert project_covered_clusters(previous, sources) == expected
    assert previous == {"claim_a": ["old", "old"], "invalid": "legacy"}
    assert sources[0]["extractions"] == {"claim_b": {}}


def test_live_coverage_rebind_uses_latest_context_and_source_records() -> None:
    old_context = {
        ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY: {"claim_old": ["prior"]}
    }
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, object()), context=old_context
    )
    records = [
        {
            "read_status": "read",
            "assessment": {"claim_id": "claim_old", "source_cluster_id": "first"},
        }
    ]
    results = ActiveResearchResultBuffers(
        query_attempts=[], selected_sources=records,
        rejected_sources=[], warnings=[],
    )
    coverage = ActiveReadCoverageContext(live=live, results=results)

    assert {item.name for item in fields(coverage)} == {"live", "results"}
    assert coverage.merge_current() == {"claim_old": {"prior", "first"}}
    old_projection = old_context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY]

    # A checkpoint may replace the entire persistence context, while source
    # publication updates the same run result buffers. Neither is cached.
    live.context = {
        ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY: {"claim_new": ["recovered"]}
    }
    results.selected_sources[:] = [
        {
            "read_status": "read",
            "assessment": {"claim_id": "claim_new", "source_cluster_id": "second"},
            "extractions": {"claim_extra": {}},
        }
    ]
    assert coverage.merge_current() == {
        "claim_new": {"recovered", "second"},
        "claim_extra": {"second"},
    }
    assert live.context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY] == {
        "claim_extra": ["second"], "claim_new": ["recovered", "second"]
    }
    assert old_projection == {"claim_old": ["first", "prior"]}


def test_live_coverage_is_idempotent_across_wave_reentry() -> None:
    live = ActiveRuntimeLiveValues(
        state=cast(ResearchState, object()), context={}
    )
    results = ActiveResearchResultBuffers(
        query_attempts=[],
        selected_sources=[{
            "read_status": "read",
            "assessment": {"claim_id": "claim_a", "source_cluster_id": "one"},
        }],
        rejected_sources=[], warnings=[],
    )
    coverage = ActiveReadCoverageContext(live=live, results=results)
    first = coverage.merge_current()
    after_first = dict(live.context)
    second = coverage.merge_current()
    assert second == first == {"claim_a": {"one"}}
    assert live.context == after_first
