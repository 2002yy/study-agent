from datetime import datetime, timezone

import pytest

from src.application.learning_review import LearningReviewService, ReviewUnavailable
from src.domain.learning_truth import (
    ClaimRevision,
    ClaimRevisionBundle,
    LearningGoal,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


class ReviewReader:
    def __init__(self):
        self.goals = {"thread": LearningGoal(id="goal")}
        self.revisions = {"goal": []}
        self.validations = {}
        self.reads = []

    def get_focus_goal(self, thread_id):
        return self.goals.get(thread_id)

    def list_goal_revisions(self, goal_id):
        return self.revisions[goal_id]

    def list_understanding_for_revision(self, revision_id):
        self.reads.append(revision_id)
        return self.validations.get(revision_id, [])

    def add(self, revision_id, claim_id, date, result="pass", goal_id="goal"):
        self.revisions[goal_id].append(
            ClaimRevisionBundle(
                ClaimRevision(id=revision_id, claim_id=claim_id, claim_text=claim_id)
            )
        )
        self.validate(revision_id, date, result)

    def validate(self, revision_id, date, result="pass"):
        evidence = UnderstandingEvidence(
            verified_at=date, user_response="private response"
        )
        self.validations.setdefault(revision_id, []).append(
            (evidence, UnderstandingClaimResult(evidence.id, revision_id, result))
        )


def test_thread_scope_and_current_revision_do_not_inherit_old_passes():
    reader = ReviewReader()
    reader.add("old", "claim", "2026-09-01T00:00:00Z")
    reader.add("new", "claim", "2026-10-01T00:00:00Z", "fail")
    reader.goals["other"] = LearningGoal(id="other-goal")
    reader.revisions["other-goal"] = []
    reader.add("other-rev", "other-claim", "2026-09-01T00:00:00Z", goal_id="other-goal")
    service = LearningReviewService(reader)
    assert service.build("thread", now=NOW).items == ()
    assert reader.reads == ["new"]
    assert service.build("other", now=NOW).items[0].claim_revision_id == "other-rev"
    assert service.build("unknown", now=NOW).goal_id == ""


def test_due_first_paging_filtering_and_no_raw_responses():
    reader = ReviewReader()
    reader.add("recent", "recent", "2026-10-01T00:00:00Z")
    reader.add("due", "due", "2026-09-26T00:00:00Z")
    reader.add("older", "older", "2026-09-01T00:00:00Z")
    service = LearningReviewService(reader)
    page = service.build("thread", now=NOW, limit=1, offset=1)
    assert page.items[0].claim_revision_id == "due"
    assert page.items[0].due
    assert page.total == 3 and page.due_count == 2
    assert "private response" not in str(page.to_dict())
    filtered = service.build("thread", now=NOW, due_only=True, offset=2)
    assert filtered.items == () and filtered.total == 2
    assert filtered.source == "derived_read_only"


def test_later_fail_does_not_reset_due_but_new_pass_does():
    reader = ReviewReader()
    reader.add("revision", "claim", "2026-09-01T00:00:00Z")
    service = LearningReviewService(reader)
    reader.validate("revision", "2026-10-01T00:00:00Z", "fail")
    assert service.build("thread", now=NOW).items[0].due
    reader.validate("revision", "2026-10-02T00:00:00Z")
    item = service.build("thread", now=NOW).items[0]
    assert not item.due
    assert item.next_review_at == "2026-10-09T00:00:00+00:00"


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (20, -1)])
def test_invalid_page_bounds_fail_before_read(limit, offset):
    with pytest.raises(ValueError, match="page bounds"):
        LearningReviewService(ReviewReader()).build(
            "thread", limit=limit, offset=offset
        )


def test_prompt_preview_is_explicit_due_revision_without_response_leak():
    reader = ReviewReader()
    reader.add("revision", "concept", "2026-09-26T00:00:00Z")
    service = LearningReviewService(reader)
    preview = service.preview_prompt("thread", "revision", now=NOW)
    assert preview.claim_revision_id == "revision" and preview.goal_id == "goal"
    assert "concept" in preview.question
    assert preview.status == "preview" and preview.source == "derived_read_only"
    assert "private response" not in str(preview.to_dict())
    assert len(reader.validations["revision"]) == 1


def test_prompt_lookup_is_not_limited_to_first_page():
    reader = ReviewReader()
    for index in range(105):
        reader.add(f"revision-{index}", f"concept-{index}", "2026-09-01T00:00:00Z")
    preview = LearningReviewService(reader).preview_prompt(
        "thread", "revision-104", now=NOW
    )
    assert preview.claim_revision_id == "revision-104"
    assert reader.reads == ["revision-104"]


@pytest.mark.parametrize("target", ["old", "foreign", "unverified", "missing"])
def test_prompt_rejects_superseded_foreign_unverified_and_missing_revisions(target):
    reader = ReviewReader()
    reader.add("old", "concept", "2026-09-01T00:00:00Z")
    reader.add("latest", "concept", "2026-09-01T00:00:00Z")
    reader.add("unverified", "another", "2026-09-01T00:00:00Z", "fail")
    reader.goals["other"] = LearningGoal(id="other-goal")
    reader.revisions["other-goal"] = []
    reader.add("foreign", "foreign", "2026-09-01T00:00:00Z", goal_id="other-goal")
    with pytest.raises(ReviewUnavailable):
        LearningReviewService(reader).preview_prompt("thread", target, now=NOW)


def test_prompt_freshly_rechecks_due_after_new_pass():
    reader = ReviewReader()
    reader.add("revision", "concept", "2026-09-01T00:00:00Z")
    service = LearningReviewService(reader)
    service.preview_prompt("thread", "revision", now=NOW)
    reader.validate("revision", "2026-10-02T00:00:00Z")
    with pytest.raises(ValueError, match="no longer due"):
        service.preview_prompt("thread", "revision", now=NOW)
