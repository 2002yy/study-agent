"""M3-QC acceptance: a preliminary answer cannot consume the whole action window.

Maps to §9.5 / P-2 of ``docs/CL_M3_CAPABILITY_CONTRACT.md``. The current dispatch checks
both ``answer_then_research`` phases against one ``started``/``timeout_seconds`` pair, so the
property under test here is precisely the one that is missing today.
"""

from __future__ import annotations

import pytest

from src.web.action_window import (
    DEFAULT_FIRST_SHARE,
    MIN_RESERVE_SECONDS,
    ActionWindow,
    split,
)


def test_the_two_phases_share_one_overall_deadline():
    window = split(started=100.0, total_seconds=30.0)
    assert window.overall_deadline == 130.0
    assert window.deadline_for(1) == window.overall_deadline


def test_the_preliminary_answer_can_never_reach_the_overall_deadline():
    """The core invariant: the reserve is structural, not dependent on good behaviour."""

    for share in (0.1, 0.3, 0.6, 0.95, 0.99):
        window = split(started=0.0, total_seconds=30.0, first_share=share)
        assert window.first_deadline < window.overall_deadline
        assert window.overall_deadline - window.first_deadline > 0


def test_a_greedy_preliminary_answer_still_leaves_time_for_research():
    window = split(started=0.0, total_seconds=5.0)
    # Simulate the answer burning its whole slice.
    now = window.first_deadline
    assert window.expired(0, now)
    assert window.remaining(1, now) > 0
    assert window.remaining(1, now) >= MIN_RESERVE_SECONDS


def test_a_short_window_is_split_without_producing_a_deadline_before_it_starts():
    window = split(started=10.0, total_seconds=0.5)
    assert window.first_deadline >= window.started
    assert window.remaining(0, window.started) > 0
    assert window.remaining(1, window.first_deadline) > 0


def test_an_extreme_share_cannot_starve_the_second_phase():
    window = split(started=0.0, total_seconds=4.0, first_share=0.99)
    assert window.reserve_seconds >= min(MIN_RESERVE_SECONDS, 2.0)
    assert window.first_deadline <= window.overall_deadline - 1.0


def test_the_default_share_matches_the_documented_value():
    assert split(started=0.0, total_seconds=10.0).first_share == DEFAULT_FIRST_SHARE


@pytest.mark.parametrize("share", [0, 1, 1.5, -0.2])
def test_a_share_that_leaves_no_reserve_is_refused(share: float):
    with pytest.raises(ValueError, match="window_first_share_must_leave_a_reserve"):
        split(started=0.0, total_seconds=10.0, first_share=share)


@pytest.mark.parametrize("total", [0, -1, -0.5])
def test_a_non_positive_window_is_refused(total: float):
    with pytest.raises(ValueError, match="window_total_must_be_positive"):
        split(started=0.0, total_seconds=total)


def test_an_unknown_phase_is_refused_instead_of_defaulting_to_the_last_one():
    window = ActionWindow(started=0.0, total_seconds=10.0)
    with pytest.raises(ValueError, match="window_phase_out_of_range"):
        window.deadline_for(2)
    with pytest.raises(ValueError, match="window_phase_out_of_range"):
        window.deadline_for(-1)


def test_remaining_time_never_goes_negative():
    window = ActionWindow(started=0.0, total_seconds=10.0)
    assert window.remaining(0, now=1_000.0) == 0.0
    assert window.expired(0, now=1_000.0)


def test_the_window_does_not_read_a_clock_of_its_own():
    """All timing is arithmetic on values the caller supplies.

    If this module read ``time.monotonic()`` itself, the split could not be tested without
    sleeping, and the host could not replay a past turn deterministically.
    """

    early = ActionWindow(started=0.0, total_seconds=10.0)
    late = ActionWindow(started=0.0, total_seconds=10.0)
    assert early.deadline_for(0) == late.deadline_for(0)
    assert early.remaining(0, now=1.0) == late.remaining(0, now=1.0)
