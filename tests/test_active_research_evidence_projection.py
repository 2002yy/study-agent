"""Small, fixture-free checks for the extracted research evidence projections."""

from __future__ import annotations

from types import SimpleNamespace

from src.application.active_research_evidence_projection import (
    _bounded_retrieval_policy,
    _evidence_brief,
    _evidence_id_for_record,
    _evidence_snapshot,
    _format_evidence_brief,
    _source_record,
)
from src.web.research.candidate_pool import CandidatePoolItem



def _eligible_state(
    evidence_id: str,
    *,
    locator: str,
    anchored_spans: tuple[str, ...],
    published_at: str,
    strength: float = 0.8,
) -> SimpleNamespace:
    """Only the shared evidence-link fixture; each source scenario stays explicit."""
    link = SimpleNamespace(
        evidence_id=evidence_id, claim_id="c1", locator=locator,
        anchored_spans=(), relation="supports", strength=strength,
        source_role="primary", source_cluster_id="cluster-1", caveats=(),
        to_dict=lambda: {"claim_id": "c1", "evidence_id": evidence_id},
    )
    return SimpleNamespace(
        evidence_links=(link,),
        evidence=(SimpleNamespace(
            evidence_id=evidence_id, extraction_status="eligible",
            anchored_spans=anchored_spans, published_at=published_at,
        ),),
        claims=(), conflict_gaps=(), gaps=(),
        budget=SimpleNamespace(to_dict=lambda: {}),
    )


def test_evidence_brief_without_gate_keeps_conditional_publication() -> None:
    state = SimpleNamespace(
        evidence_links=(), evidence=(), claims=(SimpleNamespace(id="c1", priority="critical"),),
        conflict_gaps=(), gaps=(SimpleNamespace(id="g1", state="open"),),
        budget=SimpleNamespace(to_dict=lambda: {"reads_used": 0}),
    )
    brief = _evidence_brief(state, None, [])
    assert brief["schema_version"] == "research-evidence-brief-v1"
    assert brief["eligible_evidence"] == []
    assert brief["conditional_wording_required"] is True
    assert brief["open_critical_claim_ids"] == ["c1"]
    assert brief["open_gap_ids"] == ["g1"]


def test_evidence_brief_prefers_claim_specific_extraction_anchor() -> None:
    record = {
        "candidate_id": "a1",
        "item": {"title": "Paper", "url": "https://example.org/a/"},
        "assessment": {"url": "https://EXAMPLE.org/a"},
        "read_status": "read",
        "extractions": {
            "c1": {"locator": "old-anchor", "anchored_spans": ["specific-span"]}
        },
    }
    # Use the same server-owned identity as real extraction admission.
    (ref,) = _evidence_snapshot("run-1", [record], []).refs
    assert ref.lifecycle_status == "selected"
    # Extraction acceptance must use the same URL precedence/canonicalization
    # as the server snapshot even when item and assessment spellings differ.
    assert _evidence_id_for_record("run-1", record, [record], []) == ref.id
    state = _eligible_state(ref.id, locator="old-anchor", anchored_spans=("old-span",), published_at="2026-11-17")
    brief = _evidence_brief(state, None, [record])
    row = brief["eligible_evidence"][0]
    assert row["title"] == "Paper"
    assert row["anchored_spans"] == ["specific-span"]
    assert brief["claim_links"] == [{"claim_id": "c1", "evidence_id": ref.id}]


def test_evidence_brief_never_matches_another_source_with_same_claim_locator() -> None:
    """Two pages can both have 'Section 2'; only the evidence ID identifies one."""
    sources = [
        {
            "candidate_id": "a",
            "item": {"title": "Wrong source", "url": "https://example.org/wrong"},
            "assessment": {"url": "https://example.org/wrong"},
            "read_status": "read",
            "extractions": {
                "c1": {"status": "eligible", "locator": "Section 2",
                       "anchored_spans": ["wrong-page-span"]}
            },
        },
        {
            "candidate_id": "b",
            "item": {"title": "Correct source", "url": "https://example.org/right"},
            "assessment": {"url": "https://example.org/right"},
            "read_status": "read",
            "extractions": {
                "c1": {"status": "eligible", "locator": "Section 2",
                       "anchored_spans": ["right-page-span"]}
            },
        },
    ]
    refs = _evidence_snapshot("run-1", sources, []).refs
    ref = next(item for item in refs if item.url == "https://example.org/right")
    state = _eligible_state(ref.id, locator="Section 2", anchored_spans=("fallback-span",), published_at="2026-11-20", strength=0.9)
    brief = _evidence_brief(state, None, sources)
    (row,) = brief["eligible_evidence"]
    assert row["evidence_id"] == ref.id
    assert row["url"] == "https://example.org/right"
    assert row["title"] == "Correct source"
    assert row["anchored_spans"] == ["right-page-span"]



def test_brief_keeps_source_identity_when_snapshot_dedupes_url_variants() -> None:
    sources = [
        {
            "candidate_id": "first",
            "item": {"title": "First", "url": "https://EXAMPLE.org/report/"},
            "assessment": {"url": "https://EXAMPLE.org/report/"},
            "read_status": "read",
            "extractions": {"other": {"locator": "Section 2"}},
        },
        {
            "candidate_id": "second",
            "item": {"title": "Second", "url": "https://example.org/report"},
            "assessment": {"url": "https://example.org/report"},
            "read_status": "read",
            "extractions": {
                "c1": {"locator": "Section 2", "anchored_spans": ["second-only"]}
            },
        },
    ]
    (ref,) = _evidence_snapshot("run-1", sources, []).refs
    assert ref.lifecycle_status == "selected"
    assert _evidence_id_for_record("run-1", sources[1], sources, []) == ref.id
    state = _eligible_state(ref.id, locator="Section 2", anchored_spans=("fallback",), published_at="2026-11-20")
    brief = _evidence_brief(state, None, sources)
    (row,) = brief["eligible_evidence"]
    assert row["title"] == "Second"
    assert row["url"] == "https://example.org/report"
    assert row["anchored_spans"] == ["second-only"]


def test_evidence_projection_formats_open_claims_and_conflict_warning() -> None:
    brief = {
        "gate_status": "fail",
        "eligible_evidence": [{"relation": "supports", "claim_id": "c1", "title": "Source",
                                "source_cluster_id": "s1", "strength": 0.9,
                                "locator": "p3", "url": "https://example.org/a"}],
        "open_critical_claim_ids": ["c2"],
        "unresolved_conflicts": [{"id": "conflict"}],
        "conditional_wording_required": True,
        "answer_instruction": "Keep uncertainty.",
    }
    displayed = _format_evidence_brief(brief)
    assert "Source" in displayed and "c2" in displayed
    assert "仍有未解决冲突" in displayed
    assert "只能使用条件化措辞" in displayed
    assert displayed.endswith("Keep uncertainty.")
    assert not _evidence_snapshot("run-1", [], []).refs


def test_source_record_preserves_bounded_provenance_and_legacy_export() -> None:
    from src.application import active_research_runtime

    assert active_research_runtime._source_record is _source_record
    assert active_research_runtime._bounded_retrieval_policy is _bounded_retrieval_policy
    candidate = CandidatePoolItem(
        id="candidate-1", canonical_url="https://example.org/p",
        url="https://example.org/p", title="Primary Source", snippet="",
        source="searxng", published_at="2026-11-17", query_ids=(),
        intents=(), providers=("searxng",), first_seen_rank=1,
    )
    record = _source_record(
        candidate, {"claim_id": "claim-1", "cluster_id": "cluster-1", "source_role": "primary"},
        raw_read={
            "ok": True, "status": "read", "content": "x" * 6100,
            "retrieval_policy": {"breaker_state": "closed", "failure_streak": 2},
            "read_retry": {"attempts": 2, "retry_reasons": ["timeout"]},
            "escalation": {"attempted": False, "state": "adequate"},
        },
        final_backend="native_http", retrieval_attempts=[{"backend": "native_http"}],
    )
    assert record["assessment"]["claim_id"] == "claim-1"
    assert len(record["read"]["content"]) == 6000
    assert record["retrieval_policy"]["failure_streak"] == 2
    assert record["read_retry"]["attempts"] == 2
    assert record["escalation"]["attempted"] is False
    assert record["final_backend"] == "native_http"
    assert record["retrieval_attempts"] == [{"backend": "native_http"}]
