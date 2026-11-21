"""Merge durable, run-level source-cluster coverage before planning reads.

One physical read may support several claims. Coverage must retain both the
assessment owner's claim and every claim bound by the extraction map, including
when a later wave resumes with a different set of selected sources.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY = "claim_engine_covered_clusters"


def project_covered_clusters(
    persisted_coverage: Any, selected_sources: Sequence[Mapping[str, Any]]
) -> dict[str, set[str]]:
    """Compute the historic+current coverage union without persistence.

    Keep legacy treatment of malformed persisted entries and extractable
    claims. The caller owns when (and whether) this union is written.
    """

    raw_covered = persisted_coverage
    covered_clusters_by_claim: dict[str, set[str]] = {}
    if isinstance(raw_covered, Mapping):
        for claim_id, cluster_ids in raw_covered.items():
            if isinstance(cluster_ids, (list, tuple, set)):
                covered_clusters_by_claim[str(claim_id)] = {
                    str(item) for item in cluster_ids
                }
    for covered_record in selected_sources:
        if covered_record.get("read_status") != "read":
            continue
        assessment = covered_record.get("assessment")
        if not isinstance(assessment, Mapping):
            continue
        bound_cluster = assessment.get("source_cluster_id")
        if not bound_cluster:
            continue
        bound_claims: set[str] = set()
        owner_claim = assessment.get("claim_id")
        if owner_claim:
            bound_claims.add(str(owner_claim))
        extraction_map = covered_record.get("extractions")
        if isinstance(extraction_map, Mapping):
            bound_claims.update(
                str(item) for item in extraction_map if isinstance(item, str)
            )
        for claim_id in bound_claims:
            covered_clusters_by_claim.setdefault(claim_id, set()).add(
                str(bound_cluster)
            )
    return covered_clusters_by_claim


def merge_covered_clusters(
    context: dict[str, Any], selected_sources: Sequence[Mapping[str, Any]]
) -> dict[str, set[str]]:
    """Persist the historical sorted union, exactly once at the read-plan site.

    Keep the established API for callers that supply an explicit context.
    Computation is side-effect free; this adapter owns the durable write.
    """
    covered_clusters_by_claim = project_covered_clusters(
        context.get(ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY), selected_sources
    )
    context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY] = {
        claim_id: sorted(cluster_ids)
        for claim_id, cluster_ids in sorted(covered_clusters_by_claim.items())
    }
    return covered_clusters_by_claim
