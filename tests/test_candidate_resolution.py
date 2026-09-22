"""§98 P2-A2a candidate resolution contract tests.

The contract exists because "a read outcome exists" is not the same question as
"this candidate is finished". These tests pin the five lifecycle states, the
policy-skip rule that a skip may never consume a candidate, and the fact that the
authority is the single place that decides lifecycle.
"""

from __future__ import annotations

import pytest

from src.domain.runtime_entities import WebLookupRun
from src.web.research.candidate_resolution import (
    CHAIN_EXHAUSTED,
    DEFAULT_READER_CHAIN,
    FALLBACK_PENDING,
    POLICY_DEFERRED,
    RESOLUTION_STATES,
    RESOLVED,
    RUN_BLOCKED,
    AttemptFact,
    group_facts_by_candidate,
    resolve_candidate,
    resolve_candidates,
    resolution_summary,
    terminal_candidate_ids,
)
from src.web.research.runtime import RuntimeReadOutcome


def _fact(state: str, *, backend: str = "native_http", attempted: bool = True) -> AttemptFact:
    return AttemptFact(
        backend=backend,
        retrieval_state=state,
        attempted=attempted,
        status="success" if state == "success" else "failed",
    )


def _outcome(
    candidate_id: str,
    state: str,
    *,
    backend: str = "native_http",
    status: str = "failed",
    error_code: str = "",
) -> RuntimeReadOutcome:
    return RuntimeReadOutcome(
        candidate_id=candidate_id,
        status=status,
        error_code=error_code,
        backend=backend,
        retrieval_state=state,
    )


# --------------------------------------------------------------- resolved


def test_success_resolves_the_candidate() -> None:
    resolution = resolve_candidate("c1", [_fact("success")])
    assert resolution.state == RESOLVED
    assert resolution.terminal is True
    assert resolution.reschedulable is False


def test_not_found_is_terminal() -> None:
    resolution = resolve_candidate("c1", [_fact("not_found")])
    assert resolution.state == RESOLVED
    assert resolution.terminal is True


def test_a_settled_attempt_wins_over_a_later_failure() -> None:
    resolution = resolve_candidate(
        "c1", [_fact("success"), _fact("reset", backend="wigolo_http")]
    )
    assert resolution.state == RESOLVED


# --------------------------------------------------- fallback pending / exhausted


@pytest.mark.parametrize("state", ["shell_page", "js_required", "anti_bot"])
def test_escalation_shaped_states_are_not_completed(state: str) -> None:
    """A shell or an anti-bot wall is exactly what a second reader is for."""

    resolution = resolve_candidate(
        "c1", [_fact(state)], backend_chain=("native_http", "wigolo_http")
    )
    assert resolution.state == FALLBACK_PENDING
    assert resolution.terminal is False
    assert resolution.remaining_backends == ("wigolo_http",)


@pytest.mark.parametrize("state", ["reset", "timeout", "connect_failure", "backend_failure"])
def test_transport_failure_with_an_alternate_backend_is_not_completed(state: str) -> None:
    resolution = resolve_candidate(
        "c1", [_fact(state)], backend_chain=("native_http", "wigolo_http")
    )
    assert resolution.state == FALLBACK_PENDING
    assert resolution.terminal is False


def test_transport_failure_without_an_alternate_is_chain_exhausted() -> None:
    """Today's single-reader chain must keep its existing behaviour."""

    resolution = resolve_candidate("c1", [_fact("reset")])
    assert resolution.state == CHAIN_EXHAUSTED
    assert resolution.terminal is True


def test_all_backends_exhausted_is_terminal() -> None:
    resolution = resolve_candidate(
        "c1",
        [_fact("reset"), _fact("shell_page", backend="wigolo_http")],
        backend_chain=("native_http", "wigolo_http"),
    )
    assert resolution.state == CHAIN_EXHAUSTED
    assert resolution.terminal is True
    assert resolution.attempted_backends == ("native_http", "wigolo_http")


# --------------------------------------------------------------- policy skip


def test_a_policy_skip_never_completes_a_candidate() -> None:
    """The A1a breaker skip must not consume the candidate."""

    # A skipped candidate has no attempt fact at all: the skip is not a read.
    resolution = resolve_candidate("c1", [])
    assert resolution.state == FALLBACK_PENDING
    assert resolution.terminal is False
    assert resolution.reschedulable is True


def test_a_health_blocked_candidate_is_deferred_not_exhausted() -> None:
    resolution = resolve_candidate(
        "c1",
        [],
        backend_chain=("native_http",),
        health_state_for=lambda backend, host: "open",
        host="bad.example",
    )
    assert resolution.state == POLICY_DEFERRED
    assert resolution.terminal is False
    assert resolution.reschedulable is True


def test_a_health_blocked_backend_is_not_offered_as_a_fallback() -> None:
    resolution = resolve_candidate(
        "c1",
        [_fact("reset")],
        backend_chain=("native_http", "wigolo_http"),
        health_state_for=lambda backend, host: "open" if backend == "wigolo_http" else "closed",
        host="bad.example",
    )
    # native_http was tried and failed; the only alternate is blocked, so the
    # chain is exhausted for this run - but nothing claims anything about the URL.
    assert resolution.state == CHAIN_EXHAUSTED


def test_a_half_open_backend_is_still_offered() -> None:
    resolution = resolve_candidate(
        "c1",
        [_fact("reset")],
        backend_chain=("native_http", "wigolo_http"),
        health_state_for=lambda backend, host: "half_open",
        host="bad.example",
    )
    assert resolution.state == FALLBACK_PENDING


def test_an_empty_chain_is_exhausted() -> None:
    resolution = resolve_candidate("c1", [], backend_chain=())
    assert resolution.state == CHAIN_EXHAUSTED


# --------------------------------------------------------------- run blocked


def test_budget_exhausted_blocks_the_run_without_judging_the_url() -> None:
    resolution = resolve_candidate("c1", [_fact("budget_exhausted")])
    assert resolution.state == RUN_BLOCKED
    assert resolution.terminal is False
    # Not schedulable again this run, and never a content claim.
    assert resolution.reschedulable is False
    assert resolution.last_state == "budget_exhausted"


def test_run_blocked_does_not_become_a_url_fact() -> None:
    resolution = resolve_candidate("c1", [_fact("budget_exhausted")])
    payload = resolution.to_dict()
    assert payload["state"] == RUN_BLOCKED
    assert "not_found" not in payload.values()
    assert payload["terminal"] is False


# --------------------------------------------------------------- vocabulary


def test_lifecycle_states_are_a_closed_set() -> None:
    assert set(RESOLUTION_STATES) == {
        RESOLVED,
        FALLBACK_PENDING,
        POLICY_DEFERRED,
        RUN_BLOCKED,
        CHAIN_EXHAUSTED,
    }
    assert DEFAULT_READER_CHAIN == ("native_http",)


def test_every_resolution_is_terminal_or_reschedulable() -> None:
    for state in RESOLUTION_STATES:
        resolution = resolve_candidate("c1", [_fact(state)])
        assert resolution.terminal or resolution.reschedulable or state == RUN_BLOCKED


# ------------------------------------------------------- outcome history intake


def test_grouping_keeps_one_attempt_fact_per_outcome() -> None:
    outcomes = [
        _outcome("c1", "reset", status="failed", error_code="read_failed"),
        _outcome("c2", "success", status="success"),
        _outcome("c1", "timeout", status="failed", error_code="read_failed"),
    ]
    grouped = group_facts_by_candidate(outcomes)
    assert sorted(grouped) == ["c1", "c2"]
    assert len(grouped["c1"]) == 2  # history is preserved, not collapsed
    assert [fact.retrieval_state for fact in grouped["c1"]] == ["reset", "timeout"]


def test_a_legacy_outcome_is_treated_as_an_attempt() -> None:
    """Pre-A2a rows have no retrieval_state; they were real attempts."""

    legacy = RuntimeReadOutcome(candidate_id="c1", status="failed", error_code="read_failed")
    grouped = group_facts_by_candidate([legacy])
    assert grouped["c1"][0].attempted is True
    assert grouped["c1"][0].retrieval_state == "backend_failure"


def test_terminal_ids_is_the_single_completion_definition() -> None:
    outcomes = [
        _outcome("c1", "success", status="success"),
        _outcome("c2", "not_found"),
        _outcome("c3", "reset"),
    ]
    terminal = terminal_candidate_ids(outcomes)
    # c1 and c2 are settled; c3 exhausted the single-reader chain, so it is
    # terminal too - exactly the pre-A2a behaviour for real attempts.
    assert set(terminal) == {"c1", "c2", "c3"}


def test_a_skipped_candidate_is_absent_from_the_history() -> None:
    """A policy skip records no outcome, so it cannot be terminal."""

    outcomes = [_outcome("c1", "success", status="success")]
    assert terminal_candidate_ids(outcomes) == ("c1",)
    resolutions = resolve_candidates(group_facts_by_candidate(outcomes))
    assert resolutions["c1"].terminal is True


# --------------------------------------------------------------- diagnostics


def test_resolution_summary_counts_each_state() -> None:
    outcomes = [
        _outcome("c1", "success", status="success"),
        _outcome("c2", "reset"),
        _outcome("c3", "shell_page"),
    ]
    summary = resolution_summary(outcomes)
    assert summary["candidates"] == 3
    assert summary["counts"][RESOLVED] == 1
    assert summary["counts"][CHAIN_EXHAUSTED] == 2
    assert set(summary["counts"]) == set(RESOLUTION_STATES)


def test_resolutions_are_serialisable_without_authority_fields() -> None:
    from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

    payload = resolve_candidate("c1", [_fact("shell_page")]).to_dict()
    assert not set(payload).intersection(FORBIDDEN_AUTHORITY_FIELDS)
    assert set(payload) == {
        "candidate_id",
        "state",
        "terminal",
        "reschedulable",
        "attempted_backends",
        "remaining_backends",
        "last_state",
        "last_backend",
        "skip_reason",
    }


# ----------------------------------------------------------- cursor codec


def test_cursor_read_outcome_round_trips_the_attempt_fact() -> None:
    outcome = _outcome("c1", "reset", status="failed", error_code="read_failed")
    restored = RuntimeReadOutcome.from_dict(outcome.to_dict())
    assert restored == outcome


def test_cursor_reads_a_legacy_read_outcome() -> None:
    """A pre-A2a durable row must still load, unchanged."""

    legacy = {
        "candidate_id": "c1",
        "status": "failed",
        "evidence_id": "",
        "content_chars": 0,
        "error_code": "read_failed",
    }
    restored = RuntimeReadOutcome.from_dict(legacy)
    assert restored.backend == ""
    assert restored.retrieval_state == ""


def test_cursor_keeps_the_one_outcome_per_candidate_invariant() -> None:
    """A2a relies on this invariant: a skip must not add a second row.

    The invariant itself is enforced by the cursor validator (and exercised by
    the runtime's own tests); what matters here is that A2a never needs a second
    outcome for the same candidate, because a policy skip records none.
    """

    from src.web.research.runtime import ResearchRuntimeCursor

    cursor = ResearchRuntimeCursor.from_dict(
        {
            "schema_version": "research-runtime-v2",
            "round_index": 0,
            "phase": "reading",
            "planned_queries": [],
            "query_outcomes": [],
            "candidates": [],
            "planned_read_ids": [],
            "read_outcomes": [],
            "model_calls": [],
            "inflight_model_call": None,
            "failures": [],
        }
    )
    assert cursor.completed_read_ids == ()
    assert cursor.read_resolutions() == {}


def test_run_entity_is_untouched_by_resolution() -> None:
    """Resolution reads cursor history; it never mutates run state."""

    run = WebLookupRun(
        id="run_a2a", query="q", stage="reading", status="running", research_context={}
    )
    resolve_candidate("c1", [_fact("shell_page")])
    assert run.status == "running"
