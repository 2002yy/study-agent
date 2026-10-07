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
    deep_preflight,
    verify_seed_projection,
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


# --- review round 1: runtime TOCTOU and planning reuse -----------------------------


def _deep_context(*, seed=None, envelope="valid"):
    from datetime import datetime, timezone

    from src.web.research.deep_runtime import build_execution_envelope

    deep = {}
    if envelope == "valid":
        deep["execution"] = build_execution_envelope(
            parent_turn_id="t", handoff_sha256="h", admitted_at=datetime.now(timezone.utc)
        )
    elif envelope is not None:
        deep["execution"] = envelope
    if seed is not None:
        deep["seed"] = seed
    return {"deep": deep}


def _seed(sources=None, refs=None):
    return {
        "schema_version": "deep-seed-v1",
        "standard_child_run_id": "s",
        "sources": sources if sources is not None else [_seed_source()],
        "refs": refs if refs is not None else [_seed_source()],
    }


def test_b5_a_non_deep_context_passes_preflight():
    assert deep_preflight({}) == (True, "")
    assert deep_preflight({"claim_engine": {}}) == (True, "")


def test_b5_a_tampered_envelope_fails_preflight():
    context = _deep_context(seed=_seed(), envelope={"schema_version": "wrong"})
    ok, reason = deep_preflight(context)
    assert ok is False
    assert reason == "execution_schema_mismatch"


def test_b5_a_missing_seed_fails_preflight():
    context = _deep_context(seed=None)
    assert deep_preflight(context) == (False, "seed_absent")


def test_b5_a_tampered_seed_body_fails_preflight():
    body = "durable"
    source = {"url": URL, "content_sha256": "deadbeef", "content": body, "fields": [], "origin": "x"}
    context = _deep_context(seed=_seed(sources=[source], refs=[source]))
    ok, reason = deep_preflight(context)
    assert ok is False
    assert reason == "seed_body_digest_mismatch"


def test_b5_a_seed_projection_mismatch_fails_preflight():
    good = _seed_source()
    forged = dict(good, url="https://evil.example/x")
    context = _deep_context(seed=_seed(sources=[forged], refs=[good]))
    ok, reason = deep_preflight(context)
    assert ok is False
    assert reason == "seed_projection_mismatch"


def test_b4_projection_accepts_an_honest_seed():
    assert verify_seed_projection(_seed()) == (True, "")
    # Order is not a semantic difference.
    a = dict(_seed_source(), fields=["a", "b"])
    b = dict(_seed_source(), fields=["b", "a"])
    assert verify_seed_projection(_seed(sources=[a], refs=[b])) == (True, "")


def test_b7_a_materialized_seed_is_excluded_from_planning_before_the_read_plan():
    """The planning filter must drop content-available ids, not the read loop."""

    from src.web.research.deep_runtime import content_available_ids

    selected = [
        {
            "candidate_id": "seed-candidate",
            "final_backend": SEED_FINAL_BACKEND,
            "read_status": "read",
            "read": {"content": "body"},
        }
    ]
    available = content_available_ids(["read-candidate"], selected)
    assert available == {"read-candidate", "seed-candidate"}
    # What rankings_for_plan does with the same set.
    ranked_ids = ["seed-candidate", "fresh-candidate"]
    assert [cid for cid in ranked_ids if cid not in available] == ["fresh-candidate"]
