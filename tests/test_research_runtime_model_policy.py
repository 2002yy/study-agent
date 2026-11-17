"""Frozen model policy-audit projection, independent of provider calls."""

from src.application.research_runtime_model_policy import updated_model_policy_audits


def test_model_policy_audit_filters_legacy_entries_without_mutating_input() -> None:
    original = [{"call_id": "old", "status": "allowed"}, "invalid", None]
    audits = updated_model_policy_audits(
        original,
        purpose="research_claim_planning",
        categories=("question", "source_url"),
        allowed=False,
        checked_at="2026-11-17T00:00:00Z",
    )

    assert original == [{"call_id": "old", "status": "allowed"}, "invalid", None]
    assert audits[0] == {"call_id": "old", "status": "allowed"}
    assert audits[0] is not original[0]
    assert audits[-1] == {
        "call_id": "policy:research_claim_planning:2",
        "purpose": "research_claim_planning",
        "status": "blocked_by_policy",
        "data_categories": ["question", "source_url"],
        "checked_at": "2026-11-17T00:00:00Z",
    }


def test_model_policy_audit_keeps_legacy_cap_and_sequence() -> None:
    previous = [{"call_id": f"prior-{index}"} for index in range(150)]
    audits = updated_model_policy_audits(
        previous,
        purpose="research_candidate_assessment",
        categories=(),
        allowed=True,
        checked_at="now",
    )

    assert len(audits) == 100
    assert audits[0]["call_id"] == "prior-51"
    assert audits[-2]["call_id"] == "prior-149"
    assert audits[-1]["call_id"] == "policy:research_candidate_assessment:151"
    assert audits[-1]["status"] == "allowed"
    assert len(previous) == 150
