"""Deep-2 runtime seams: seed candidates, local materialization and no re-reading.

These test the runtime-side helpers directly, because that is where the Deep-2 invariants live:
a seed must reach assessment as an ordinary candidate, it must never be pre-marked as a
completed read, its materialization must not look like a physical read, and it must never be
fetched again - not by a later wave and not by the lead-read path.
"""

from __future__ import annotations

import hashlib

from src.application.active_research_runtime import (
    _bind_deep_seed_candidates,
    _deep_seed_materialization,
    _lead_read_plan,
)
from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchQuestion,
    build_research_state,
)
from src.web.research.deep_runtime import (
    SEED_DISCOVERY_METHOD,
    SEED_FINAL_BACKEND,
    SEED_PROVIDER,
    seed_candidate_identity,
)
from src.web.research.runtime import ResearchRuntimeCursor

BODY = "Python 3.14.0 was released on 2025-10-07."
SHA = hashlib.sha256(BODY.encode()).hexdigest()
URL = "https://www.python.org/downloads/release/python-3140/"


def _state():
    requirement = EvidenceRequirement(
        min_independent_sources=1,
        requires_primary_source=False,
    )
    claim = ResearchClaim(
        id="c1",
        question_id="q1",
        text="Python 3.14.0 was released on 2025-10-07",
        kind="factual",
        priority="critical",
        state="unresolved",
        evidence_requirement=requirement,
    )
    gap = EvidenceGap(id="g1", claim_id="c1", gap_type="missing_evidence", state="open")
    return build_research_state(
        mode="active",
        questions=(ResearchQuestion(id="q1", question_surface="release date?"),),
        claims=(claim,),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(gap,),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=40,
            max_reads=12,
            soft_timeout_seconds=120,
            hard_timeout_seconds=180,
            max_total_chars=80_000,
        ),
        known_evidence_ids=(),
        reference_date="2026-10-07",
    )


def _cursor_with_queries(state):
    from src.application.active_research_runtime import _append_gap_queries

    return _append_gap_queries(ResearchRuntimeCursor(), state)


def _seed_source(url=URL, body=BODY):
    return {
        "url": url,
        "content_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "content": body,
        "fields": ["release_date"],
        "origin": "standard",
    }


# --- E14 / E15 / E16 / E18: the seed becomes an ordinary candidate ----------------


def test_e15_the_seed_is_bound_to_this_wave_actionable_queries():
    state = _state()
    cursor = _cursor_with_queries(state)
    assert cursor.planned_queries, "fixture needs a planned query"

    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    assert len(bound.candidates) == 1
    seed_candidate = bound.candidates[0]
    assert seed_candidate.query_ids, "a seed with no query ids never reaches assessment"
    planned_ids = {item.id for item in bound.planned_queries if item.claim_id == "c1"}
    assert planned_ids.intersection(seed_candidate.query_ids)


def test_e14_the_seed_is_not_marked_as_a_completed_read():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    # A pre-marked completed read would be excluded from the assessment window.
    assert bound.completed_read_ids == ()
    assert bound.read_outcomes == ()


def test_seed_candidate_identity_and_provenance():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    candidate = bound.candidates[0]
    assert candidate.id == seed_candidate_identity(URL)
    assert candidate.url == URL
    assert candidate.discovery_method == SEED_DISCOVERY_METHOD
    assert SEED_PROVIDER in candidate.providers


def test_e18_the_seed_occupies_the_candidate_budget():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=1
    )
    assert len(bound.candidates) == 1
    over = _bind_deep_seed_candidates(
        cursor,
        state,
        seed_by_url={URL: _seed_source(), "https://other/x": _seed_source("https://other/x")},
        max_candidates=1,
    )
    assert len(over.candidates) == 1


def test_e19_a_second_binding_merges_into_the_same_candidate():
    state = _state()
    cursor = _cursor_with_queries(state)
    first = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    second = _bind_deep_seed_candidates(
        first, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    assert len(second.candidates) == 1
    assert second.candidates[0].id == first.candidates[0].id


def test_an_empty_seed_leaves_the_cursor_untouched():
    state = _state()
    cursor = _cursor_with_queries(state)
    assert _bind_deep_seed_candidates(cursor, state, seed_by_url={}, max_candidates=40) is cursor


# --- E28 / E29: materialization looks like content, not like a fetch ---------------


def _plan_item(candidate):
    return {
        "candidate_id": candidate.id,
        "claim_id": "c1",
        "cluster_id": "cluster-1",
        "source_role": "primary",
    }


def test_e28_e29_the_materialized_source_is_read_backed_without_a_retrieval_state():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    candidate = bound.candidates[0]
    selected: list[dict] = []

    record = _deep_seed_materialization(
        candidate=_to_pool_item(candidate),
        plan_item=_plan_item(candidate),
        seed_source=_seed_source(),
        source_limit=6000,
        selected_sources=selected,
    )

    assert record is not None
    assert record["read_status"] == "read"
    assert record["final_backend"] == SEED_FINAL_BACKEND
    assert record["materialization"]["schema_version"] == "deep-seed-materialization-v1"
    assert record["materialization"]["origin"] == "standard_seed"
    assert record["materialization"]["source_content_sha256"] == SHA
    # No retrieval happened, so no retrieval state and no attempt history are invented.
    assert "retrieval_state" not in record
    assert "retrieval_attempts" not in record
    assert selected and selected[0]["candidate_id"] == candidate.id


def test_materialization_respects_the_char_budget():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    candidate = bound.candidates[0]
    selected: list[dict] = []
    record = _deep_seed_materialization(
        candidate=_to_pool_item(candidate),
        plan_item=_plan_item(candidate),
        seed_source=_seed_source(),
        source_limit=5,
        selected_sources=selected,
    )
    assert record is not None
    assert record["read"]["content"] == BODY[:5]
    assert record["materialization"]["truncated"] is True
    assert record["materialization"]["materialized_chars"] == 5


def test_materialization_declines_when_no_budget_remains():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    candidate = bound.candidates[0]
    assert (
        _deep_seed_materialization(
            candidate=_to_pool_item(candidate),
            plan_item=_plan_item(candidate),
            seed_source=_seed_source(),
            source_limit=0,
            selected_sources=[],
        )
        is None
    )


# --- E34: the lead-read path never touches a seed ---------------------------------


def test_e34_seed_backed_candidates_are_excluded_from_lead_reads():
    state = _state()
    cursor = _cursor_with_queries(state)
    bound = _bind_deep_seed_candidates(
        cursor, state, seed_by_url={URL: _seed_source()}, max_candidates=40
    )
    seed_ids = frozenset(item.id for item in bound.candidates)
    assert seed_ids

    with_exclusion = _lead_read_plan(
        state,
        {},
        completed_read_ids=(),
        lead_read_ids=(),
        lead_budget_available=True,
        seed_backed_ids=seed_ids,
    )
    assert with_exclusion == []


def _to_pool_item(candidate):
    from src.application.active_research_runtime import _candidate_item

    return _candidate_item(candidate)
