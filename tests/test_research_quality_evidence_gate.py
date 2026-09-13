from __future__ import annotations

from dataclasses import replace

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
from src.web.research.evidence_gate import (
    claim_support_topology,
    evaluate_evidence_gate,
)
from src.web.research.policy import evidence_policy_for_claim


def _budget(*, exhausted: bool = False) -> ResearchBudget:
    return ResearchBudget(
        20,
        8,
        45,
        60,
        16000,
        candidates_used=20 if exhausted else 2,
        reads_used=2,
        elapsed_seconds=10,
    )


def _state(
    *,
    evidence: tuple[ResearchEvidence, ...] = (),
    links: tuple[ResearchClaimEvidenceLink, ...] = (),
    clusters: tuple[EvidenceCluster, ...] = (),
    claim_state: str = "searching",
    profile: str = "current_fact",
    budget: ResearchBudget | None = None,
    include_gap: bool = True,
    max_age_days: int | None = None,
    requires_dated_evidence: bool = False,
    reference_date: str = "",
) -> ResearchState:
    policy = evidence_policy_for_claim(
        kind="factual",
        priority="critical",
        profile=profile,  # type: ignore[arg-type]
    )
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
                claim_state,  # type: ignore[arg-type]
                replace(
                    policy.requirement,
                    max_age_days=max_age_days,
                    requires_dated_evidence=requires_dated_evidence,
                ),
            )
        ],
        evidence=evidence,
        evidence_links=links,
        source_clusters=clusters,
        gaps=(EvidenceGap("gap1", "claim1", "evidence_missing"),) if include_gap else (),
        conflict_gaps=(),
        budget=budget or _budget(),
        known_evidence_ids={item.evidence_id for item in evidence},
        reference_date=reference_date,
    )


def _evidence(
    evidence_id: str,
    *,
    lifecycle: str = "read",
    extraction: str = "eligible",
    published_at: str = "",
) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id,
        lifecycle_status=lifecycle,  # type: ignore[arg-type]
        extraction_status=extraction,  # type: ignore[arg-type]
        published_at=published_at,
    )


def _link(
    evidence_id: str,
    *,
    cluster: str,
    relation: str = "supports",
    role: str = "independent_secondary",
    strength: float = 0.9,
) -> ResearchClaimEvidenceLink:
    return ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("claim1", evidence_id, relation, strength),
        source_role=role,
        source_cluster_id=cluster,
    )


def test_critical_claim_without_eligible_evidence_blocks() -> None:
    result = evaluate_evidence_gate(_state(claim_state="satisfied"))

    assert result.status == "block"
    assert result.allows_stop is False
    assert result.open_critical_claims == ("claim1",)
    assert "critical:claim1:eligible_support_clusters=0/2" in result.reasons


def test_snippet_only_and_failed_extraction_never_satisfy_critical_claim() -> None:
    records = (
        _evidence("ev_candidate", lifecycle="candidate"),
        _evidence("ev_failed", extraction="extractor_failed"),
    )
    links = (
        _link("ev_candidate", cluster="cluster1"),
        _link("ev_failed", cluster="cluster2"),
    )
    clusters = (
        EvidenceCluster("cluster1", ("ev_candidate",)),
        EvidenceCluster("cluster2", ("ev_failed",)),
    )

    result = evaluate_evidence_gate(_state(evidence=records, links=links, clusters=clusters))

    assert result.status == "block"
    assert result.eligible_evidence_ids == ()


def test_duplicate_source_cluster_counts_once() -> None:
    records = (_evidence("ev1"), _evidence("ev2"))
    links = (
        _link("ev1", cluster="same_origin"),
        _link("ev2", cluster="same_origin"),
    )
    clusters = (EvidenceCluster("same_origin", ("ev1", "ev2")),)

    result = evaluate_evidence_gate(_state(evidence=records, links=links, clusters=clusters))

    assert result.status == "block"
    assert "critical:claim1:eligible_support_clusters=1/2" in result.reasons


def test_stale_evidence_cannot_satisfy_freshness_requirement() -> None:
    records = (_evidence("ev_old", published_at="2024-01-01"),)
    links = (_link("ev_old", cluster="official", role="primary"),)
    clusters = (EvidenceCluster("official", ("ev_old",)),)

    result = evaluate_evidence_gate(
        _state(
            evidence=records,
            links=links,
            clusters=clusters,
            profile="official_statement",
            max_age_days=180,
            requires_dated_evidence=True,
            reference_date="2026-08-01",
        )
    )

    assert result.status == "block"
    assert "critical:claim1:freshness_required" in result.reasons


def test_fresh_dated_evidence_can_satisfy_freshness_requirement() -> None:
    records = (_evidence("ev_current", published_at="2026-07-01"),)
    links = (_link("ev_current", cluster="official", role="primary"),)
    clusters = (EvidenceCluster("official", ("ev_current",)),)

    result = evaluate_evidence_gate(
        _state(
            evidence=records,
            links=links,
            clusters=clusters,
            profile="official_statement",
            max_age_days=180,
            requires_dated_evidence=True,
            reference_date="2026-08-01",
        )
    )

    assert result.status == "pass"


def test_two_independent_read_clusters_pass() -> None:
    records = (_evidence("ev1"), _evidence("ev2", lifecycle="selected"))
    links = (
        _link("ev1", cluster="cluster1"),
        _link("ev2", cluster="cluster2"),
    )
    clusters = (
        EvidenceCluster("cluster1", ("ev1",)),
        EvidenceCluster("cluster2", ("ev2",)),
    )

    result = evaluate_evidence_gate(_state(evidence=records, links=links, clusters=clusters))

    assert result.status == "pass"
    assert result.allows_stop is True
    assert result.open_critical_claims == ()
    assert result.eligible_evidence_ids == ("ev1", "ev2")


def test_official_statement_requires_primary_role() -> None:
    record = (_evidence("ev1"),)
    cluster = (EvidenceCluster("cluster1", ("ev1",)),)
    secondary = (_link("ev1", cluster="cluster1"),)
    primary = (_link("ev1", cluster="cluster1", role="primary"),)

    blocked = evaluate_evidence_gate(
        _state(evidence=record, links=secondary, clusters=cluster, profile="official_statement")
    )
    passed = evaluate_evidence_gate(
        _state(evidence=record, links=primary, clusters=cluster, profile="official_statement")
    )

    assert blocked.status == "block"
    assert "critical:claim1:primary_required" in blocked.reasons
    assert passed.status == "pass"


def test_strong_support_and_contradiction_create_conflict_and_block() -> None:
    records = (_evidence("ev_support"), _evidence("ev_contradict"))
    links = (
        _link("ev_support", cluster="cluster1"),
        _link(
            "ev_contradict",
            cluster="cluster2",
            relation="contradicts",
        ),
    )
    clusters = (
        EvidenceCluster("cluster1", ("ev_support",)),
        EvidenceCluster("cluster2", ("ev_contradict",)),
    )

    result = evaluate_evidence_gate(_state(evidence=records, links=links, clusters=clusters))

    assert result.status == "block"
    assert result.conflicts[0].id == "gate_conflict_claim1"
    assert result.conflicts[0].supporting_evidence_ids == ("ev_support",)
    assert result.conflicts[0].contradicting_evidence_ids == ("ev_contradict",)


def test_unavailable_is_not_satisfied_even_with_enough_evidence() -> None:
    records = (_evidence("ev1"), _evidence("ev2"))
    links = (
        _link("ev1", cluster="cluster1"),
        _link("ev2", cluster="cluster2"),
    )
    clusters = (
        EvidenceCluster("cluster1", ("ev1",)),
        EvidenceCluster("cluster2", ("ev2",)),
    )

    result = evaluate_evidence_gate(
        _state(
            evidence=records,
            links=links,
            clusters=clusters,
            claim_state="unavailable",
        )
    )

    assert result.status == "block"
    assert "critical:claim1:unavailable_not_satisfied" in result.reasons


def test_budget_exhaustion_returns_partial_without_false_satisfaction() -> None:
    result = evaluate_evidence_gate(_state(budget=_budget(exhausted=True)))

    assert result.status == "partial"
    assert result.allows_stop is True
    assert result.open_critical_claims == ("claim1",)
    assert "budget:hard_exhausted_with_open_critical_claims" in result.reasons


def test_open_critical_claim_without_gap_is_explicit() -> None:
    result = evaluate_evidence_gate(_state(include_gap=False))

    assert result.gap_ids == ()
    assert "critical:claim1:evidence_gap_missing" in result.reasons


def test_empty_claim_graph_cannot_false_close() -> None:
    state = build_research_state(
        mode="shadow",
        questions=(),
        claims=(),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=_budget(),
        known_evidence_ids=(),
    )

    result = evaluate_evidence_gate(state)

    assert result.status == "block"
    assert result.allows_stop is False
    assert result.reasons == ("claim_graph:no_critical_claims",)


def test_resolved_gap_does_not_hide_missing_active_gap() -> None:
    state = _state()
    resolved = EvidenceGap(
        "gap1",
        "claim1",
        "evidence_missing",
        state="resolved",
    )
    state = build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=state.claims,
        evidence=state.evidence,
        evidence_links=state.evidence_links,
        source_clusters=state.source_clusters,
        gaps=(resolved,),
        conflict_gaps=state.conflict_gaps,
        budget=state.budget,
        known_evidence_ids=(),
    )

    result = evaluate_evidence_gate(state)

    assert result.gap_ids == ()
    assert "critical:claim1:evidence_gap_missing" in result.reasons


def test_claim_support_topology_matches_gate_reasons() -> None:
    """Slice 4 drift guard: the shared topology helper agrees with the Gate."""

    state = _state(
        evidence=(_evidence("ev1"),),
        links=(_link("ev1", cluster="c1", role="primary"),),
        clusters=(EvidenceCluster("c1", ("ev1",)),),
    )
    clusters, required, has_primary = claim_support_topology(state, state.claims[0])
    gate = evaluate_evidence_gate(state)

    assert clusters == 1
    assert required == 2
    assert has_primary is True
    assert (
        f"eligible_support_clusters={clusters}/{required}"
        in " ".join(gate.reasons)
    )
    assert "primary_required" not in " ".join(gate.reasons)


def test_lead_discovery_gap_triggers_on_partial_independent_cluster_coverage() -> None:
    from src.application.active_research_runtime import _claim_has_discovery_gap

    state = _state(
        evidence=(_evidence("ev1"),),
        links=(_link("ev1", cluster="c1", role="primary"),),
        clusters=(EvidenceCluster("c1", ("ev1",)),),
    )

    # primary present, but only 1/2 independent support clusters.
    assert _claim_has_discovery_gap(state, state.claims[0]) is True


def test_lead_discovery_gap_cluster_branch_requires_partial_coverage() -> None:
    """0/N must not be treated as an independent-cluster discovery gap."""

    state = _state()
    clusters, required, has_primary = claim_support_topology(state, state.claims[0])

    assert clusters == 0
    assert required == 2
    assert has_primary is False
    # The cluster branch is 0 < clusters < required, so 0/N cannot trigger it.
    assert (0 < clusters < required) is False


def test_lead_discovery_gap_is_false_when_topology_is_satisfied() -> None:
    from src.application.active_research_runtime import _claim_has_discovery_gap

    state = _state(
        evidence=(_evidence("ev1"), _evidence("ev2")),
        links=(
            _link("ev1", cluster="c1", role="primary"),
            _link("ev2", cluster="c2", role="independent_secondary"),
        ),
        clusters=(
            EvidenceCluster("c1", ("ev1",)),
            EvidenceCluster("c2", ("ev2",)),
        ),
    )

    assert _claim_has_discovery_gap(state, state.claims[0]) is False
