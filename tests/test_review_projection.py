"""§169-B: the review projection is derived, read-only and time-based."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.application.review_projection import (
    REASON_DUE,
    REASON_NOT_DUE,
    REVIEW_INTERVAL,
    due_reviews,
    project_review,
)
from src.domain.learning_truth import (
    UnderstandingClaimResult,
    UnderstandingEvidence,
)

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _pair(revision_id: str, *, verified_at: str, result: str = "pass"):
    return (
        UnderstandingEvidence(id=f"u-{revision_id}", verified_at=verified_at),
        UnderstandingClaimResult(
            understanding_evidence_id=f"u-{revision_id}",
            claim_revision_id=revision_id,
            result=result,
        ),
    )


def test_recent_validation_is_not_due():
    recent = (NOW - timedelta(days=1)).isoformat()
    (item,) = project_review([_pair("rev-1", verified_at=recent)], now=NOW)
    assert item.due is False
    assert item.reason == REASON_NOT_DUE
    assert item.claim_revision_id == "rev-1"


def test_old_validation_is_due():
    old = (NOW - REVIEW_INTERVAL - timedelta(hours=1)).isoformat()
    (item,) = project_review([_pair("rev-1", verified_at=old)], now=NOW)
    assert item.due is True
    assert item.reason == REASON_DUE


def test_exactly_at_the_boundary_is_due():
    boundary = (NOW - REVIEW_INTERVAL).isoformat()
    (item,) = project_review([_pair("rev-1", verified_at=boundary)], now=NOW)
    assert item.due is True


def test_latest_pass_wins_over_an_older_pass():
    older = (NOW - timedelta(days=30)).isoformat()
    newer = (NOW - timedelta(days=1)).isoformat()
    (item,) = project_review(
        [_pair("rev-1", verified_at=older), _pair("rev-1", verified_at=newer)],
        now=NOW,
    )
    assert item.due is False, "the most recent validation governs"


def test_a_later_failure_does_not_demote_or_erase_validation():
    passed = (NOW - timedelta(days=2)).isoformat()
    failed_later = (NOW - timedelta(days=1)).isoformat()
    (item,) = project_review(
        [
            _pair("rev-1", verified_at=passed),
            _pair("rev-1", verified_at=failed_later, result="fail"),
        ],
        now=NOW,
    )
    # The pass still counts and the failure is ignored for due calculation.
    assert item.due is False
    assert item.last_validated_at.startswith(passed[:19])


def test_only_confirmed_understanding_is_reviewable():
    failing = (NOW - timedelta(days=30)).isoformat()
    assert project_review([_pair("rev-1", verified_at=failing, result="fail")], now=NOW) == ()
    assert project_review([_pair("rev-1", verified_at=failing, result="partial")], now=NOW) == ()


def test_empty_input_projects_nothing():
    assert project_review([], now=NOW) == ()


def test_due_reviews_filters_to_the_due_subset():
    old = (NOW - timedelta(days=30)).isoformat()
    recent = (NOW - timedelta(days=1)).isoformat()
    projections = project_review(
        [_pair("rev-old", verified_at=old), _pair("rev-new", verified_at=recent)],
        now=NOW,
    )
    assert [p.claim_revision_id for p in due_reviews(projections)] == ["rev-old"]


def test_projection_is_immutable():
    from dataclasses import FrozenInstanceError

    import pytest

    old = (NOW - timedelta(days=30)).isoformat()
    (item,) = project_review([_pair("rev-1", verified_at=old)], now=NOW)
    with pytest.raises(FrozenInstanceError):
        item.due = False  # type: ignore[misc]
