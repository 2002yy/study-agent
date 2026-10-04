"""§174.3.1: the per-candidate resolution trace is observation-only and explainable.

It must let a later run with ``candidate_count > 0`` and ``attempted_reads == 0`` be
explained offline, without changing any decision.
"""

from __future__ import annotations

from src.web.research.candidate_resolution import (
    NOT_OBSERVED,
    candidate_resolution_trace,
    group_facts_by_candidate,
    resolve_candidates,
    resolution_summary,
)


def _outcome(cid, *, state="", attempted=True, backend="", error_code="", status=""):
    return {
        "candidate_id": cid,
        "retrieval_state": state,
        "attempted": attempted,
        "backend": backend,
        "error_code": error_code,
        "status": status,
    }


def _skipped(cid, reason="policy_x", backend=""):
    return _outcome(
        cid, attempted=False, backend=backend, error_code=f"read_skipped:{reason}"
    )


# --- zero-read explainability --------------------------------------------------


def test_zero_reads_are_explained_by_state_counts():
    outcomes = [_skipped(f"c{i}") for i in range(10)]
    trace = candidate_resolution_trace(outcomes, backend_chain=())
    assert trace["candidate_count"] == 10
    assert trace["attempted_reads"] == 0
    assert trace["zero_read_reason_summary"] == "0 reads = 10\u00d7chain_exhausted"
    assert all(e["entered_read"] is False for e in trace["candidates"])
    assert all(e["blocking_stage"] == "backend_chain" for e in trace["candidates"])


def test_zero_read_summary_names_the_mixed_composition():
    outcomes = [
        _skipped("a"),  # chain_exhausted (empty chain)
        _skipped("b"),
        _outcome("c", state="budget_exhausted", backend="x"),  # run_blocked
    ]
    trace = candidate_resolution_trace(outcomes, backend_chain=())
    assert trace["attempted_reads"] == 1  # the budget-blocked one did attempt
    assert trace["zero_read_reason_summary"] == ""
    assert trace["state_counts"] == {"chain_exhausted": 2, "run_blocked": 1}


def test_skipped_candidate_reports_its_policy_reason():
    trace = candidate_resolution_trace(
        [_skipped("a", reason="locale_mismatch")], backend_chain=()
    )
    entry = trace["candidates"][0]
    assert entry["skip_reason"] == "locale_mismatch"
    assert entry["defer_reason"] == ""


# --- candidates that entered a read --------------------------------------------


def test_a_read_candidate_is_marked_and_not_a_zero_read():
    outcomes = [_outcome("a", state="success", backend="native_http", status="success")]
    trace = candidate_resolution_trace(outcomes, backend_chain=("native_http",))
    entry = trace["candidates"][0]
    assert entry["entered_read"] is True
    assert entry["blocking_stage"] == ""
    assert entry["final_status"] == "selected"
    assert trace["attempted_reads"] == 1
    assert trace["zero_read_reason_summary"] == ""


def test_failed_read_is_rejected_not_selected():
    outcomes = [_outcome("a", state="not_found", backend="native_http")]
    trace = candidate_resolution_trace(outcomes, backend_chain=("native_http",))
    entry = trace["candidates"][0]
    assert entry["entered_read"] is True
    assert entry["final_status"] == "rejected"


# --- planned candidates without outcomes ---------------------------------------


def test_planned_candidate_without_outcome_is_not_observed():
    trace = candidate_resolution_trace(
        [_skipped("a")], candidate_ids=["a", "b"], backend_chain=()
    )
    by_id = {e["candidate_id"]: e for e in trace["candidates"]}
    assert by_id["b"]["state"] == NOT_OBSERVED
    assert by_id["b"]["blocking_stage"] == NOT_OBSERVED
    assert by_id["b"]["entered_read"] is False
    assert trace["candidate_count"] == 2
    # The unobserved candidate is still visible, so a count mismatch never hides.
    assert trace["state_counts"]["not_observed"] == 1


# --- observation-only guarantee ------------------------------------------------


def test_trace_does_not_change_existing_decisions():
    outcomes = [_skipped(f"c{i}") for i in range(5)]
    grouped = group_facts_by_candidate(outcomes)
    before = {k: v.state for k, v in resolve_candidates(grouped, backend_chain=()).items()}
    before_summary = resolution_summary(outcomes, backend_chain=())
    candidate_resolution_trace(outcomes, backend_chain=())
    after = {k: v.state for k, v in resolve_candidates(grouped, backend_chain=()).items()}
    assert before == after
    assert resolution_summary(outcomes, backend_chain=()) == before_summary


def test_trace_does_not_mutate_its_inputs():
    outcomes = [_skipped("a")]
    snapshot = [dict(o) for o in outcomes]
    candidate_resolution_trace(outcomes, backend_chain=())
    assert outcomes == snapshot
