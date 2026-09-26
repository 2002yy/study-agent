"""Phase-budget admission fault injection (RQ1-C Phase Budget & Scheduling).

Frozen scenarios (user-specified):
- ~35s left  -> a direct deeper-URL follow-up is still affordable
- ~18s left  -> a generic hint follow-up is denied
- ~10s left  -> finalization only
- reads == 1 -> a branch whose complete chain needs more reads is denied
- calls == 1 -> a multi-stage branch is denied even when time looks fine
"""

from __future__ import annotations

from src.web.research.phase_budget import (
    FINALIZATION_RESERVE_SECONDS,
    PhaseBudget,
    admit_phase_action,
)

SOFT = 45.0
HARD = 60.0


def _budget(
    *,
    elapsed: float,
    reads: int = 8,
    calls: int = 8,
) -> PhaseBudget:
    return PhaseBudget(
        elapsed_seconds=elapsed,
        soft_timeout_seconds=SOFT,
        hard_timeout_seconds=HARD,
        remaining_reads=reads,
        remaining_model_calls=calls,
    )


def test_direct_url_followup_is_affordable_with_thirty_five_seconds_left() -> None:
    budget = _budget(elapsed=25.0)  # 35s remaining

    admission = admit_phase_action(budget, action_type="evidence_lead_direct_url")

    assert admission.admitted is True
    assert admission.reason == "admitted"
    assert admission.priority == 2
    assert admission.required_reads == 1
    assert admission.required_model_calls == 1


def test_generic_hint_followup_is_denied_with_eighteen_seconds_left() -> None:
    budget = _budget(elapsed=42.0)  # 18s remaining -> 6s of research budget

    admission = admit_phase_action(budget, action_type="evidence_lead_hint_query")

    assert admission.admitted is False
    assert admission.reason == "skipped_insufficient_phase_budget"
    assert admission.priority == 4
    assert admission.estimated_seconds == 28.0


def test_everything_is_denied_inside_the_finalization_reserve() -> None:
    budget = _budget(elapsed=50.0)  # 10s remaining

    assert budget.in_finalization_reserve is True
    assert FINALIZATION_RESERVE_SECONDS == 12.0
    for action in (
        "evidence_read",
        "conflict_read",
        "evidence_lead_direct_url",
        "evidence_lead_trusted_domain",
        "evidence_lead_hint_query",
        "candidate_lead",
    ):
        admission = admit_phase_action(budget, action_type=action)  # type: ignore[arg-type]
        assert admission.admitted is False, action
        assert admission.reason == "finalization_reserve"


def test_read_budget_blocks_a_branch_that_needs_a_read() -> None:
    budget = _budget(elapsed=25.0, reads=0)

    admission = admit_phase_action(budget, action_type="evidence_read")

    assert admission.admitted is False
    assert admission.reason == "insufficient_read_budget"


def test_model_call_budget_separates_stages_even_when_time_is_plenty() -> None:
    # 42s remaining -> 30s of research budget: enough time for both chains.
    budget = _budget(elapsed=18.0, calls=1)

    direct = admit_phase_action(budget, action_type="evidence_lead_direct_url")
    hint = admit_phase_action(budget, action_type="evidence_lead_hint_query")

    # A direct URL needs one model call (extraction) and is still affordable.
    assert direct.admitted is True
    # The hint chain needs assessment + extraction; one call is not enough.
    assert hint.admitted is False
    assert hint.reason == "insufficient_model_budget"


def test_soft_deadline_stops_low_priority_expansion_before_the_reserve() -> None:
    budget = _budget(elapsed=46.0)  # past soft deadline, 14s remaining (outside reserve)

    assert budget.past_soft_deadline is True
    assert budget.in_finalization_reserve is False

    # Past the soft deadline the low-yield expansion actions are refused by the
    # priority gate itself (their reason is not a plain time shortfall).
    for action in (
        "evidence_lead_trusted_domain",
        "evidence_lead_hint_query",
        "candidate_lead",
    ):
        admission = admit_phase_action(budget, action_type=action)  # type: ignore[arg-type]
        assert admission.admitted is False, action
        assert admission.reason == "past_soft_deadline", action

    # P0/P1 are still evaluated on their own merits; with only 14s left the
    # 10s-chain is refused because the finalization reserve is protected first.
    for action in ("evidence_read", "conflict_read"):
        admission = admit_phase_action(budget, action_type=action)  # type: ignore[arg-type]
        assert admission.admitted is False, action
        assert admission.reason == "skipped_insufficient_phase_budget", action


def test_candidate_lead_discovery_requires_the_largest_tail() -> None:
    budget = _budget(elapsed=25.0)  # 35s remaining, 23s of research budget

    # candidate_lead needs 24s of research budget -> not affordable at 23s.
    admission = admit_phase_action(budget, action_type="candidate_lead")

    assert admission.admitted is False
    assert admission.reason == "skipped_insufficient_phase_budget"
    assert admission.priority == 5
