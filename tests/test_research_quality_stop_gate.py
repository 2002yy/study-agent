from __future__ import annotations

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceGap,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.policy import evidence_policy_for_claim
from src.web.research.stop_gate import (
    evaluate_shadow_stop,
)


def _state(*, supported: bool, exhausted: bool = False) -> ResearchState:
    policy = evidence_policy_for_claim(
        kind="factual",
        priority="critical",
        profile="current_fact",
    )
    evidence = (
        ResearchEvidence(
            "ev1",
            lifecycle_status="read",
            extraction_status="eligible",
        ),
        ResearchEvidence(
            "ev2",
            lifecycle_status="selected",
            extraction_status="eligible",
        ),
    ) if supported else ()
    links = (
        ResearchClaimEvidenceLink(
            ClaimEvidenceLinkV1("claim1", "ev1", "supports", 0.9),
            source_role="independent_secondary",
            source_cluster_id="cluster1",
        ),
        ResearchClaimEvidenceLink(
            ClaimEvidenceLinkV1("claim1", "ev2", "supports", 0.8),
            source_role="authoritative_secondary",
            source_cluster_id="cluster2",
        ),
    ) if supported else ()
    clusters = (
        EvidenceCluster("cluster1", ("ev1",)),
        EvidenceCluster("cluster2", ("ev2",)),
    ) if supported else ()
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "What is verified?", "critical")],
        claims=[
            ResearchClaim(
                "claim1",
                "q1",
                "A critical factual claim.",
                "factual",
                "critical",
                "searching",
                policy.requirement,
            )
        ],
        evidence=evidence,
        evidence_links=links,
        source_clusters=clusters,
        gaps=(EvidenceGap("gap1", "claim1", "missing_support"),),
        conflict_gaps=(),
        budget=ResearchBudget(
            20,
            8,
            45,
            60,
            16000,
            candidates_used=20 if exhausted else 2,
            reads_used=2,
            elapsed_seconds=10,
        ),
        known_evidence_ids={item.evidence_id for item in evidence},
    )


def test_shadow_block_records_false_closure_candidate_without_overriding_legacy() -> None:
    result = evaluate_shadow_stop(_state(supported=False), legacy_would_stop=True)

    assert result.shadow_status == "block"
    assert result.shadow_would_block is True
    assert result.legacy_would_stop_but_shadow_blocked is True
    assert result.legacy_should_stop is True
    assert result.open_critical_claims == ("claim1",)


def test_shadow_pass_preserves_legacy_stop() -> None:
    result = evaluate_shadow_stop(_state(supported=True), legacy_would_stop=True)

    assert result.shadow_status == "pass"
    assert result.shadow_would_pass is True
    assert result.legacy_would_stop_but_shadow_blocked is False
    assert result.legacy_should_stop is True


def test_shadow_block_is_not_false_closure_when_legacy_would_continue() -> None:
    result = evaluate_shadow_stop(_state(supported=False), legacy_would_stop=False)

    assert result.shadow_would_block is True
    assert result.legacy_would_stop_but_shadow_blocked is False
    assert result.legacy_should_stop is False


def test_budget_partial_is_not_reported_as_shadow_block() -> None:
    result = evaluate_shadow_stop(
        _state(supported=False, exhausted=True),
        legacy_would_stop=True,
    )

    assert result.shadow_status == "partial"
    assert result.shadow_would_pass is True
    assert result.shadow_would_block is False
    assert result.open_critical_claims == ("claim1",)
