"""Frozen model policy admission/audit, independent of provider calls."""

import pytest

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_model_policy import (
    ACTIVE_RESEARCH_POLICY_AUDITS_KEY,
    RuntimeModelPolicyContext,
    updated_model_policy_audits,
)
from src.web.research.contracts import ResearchState
from typing import cast


def _live(context: dict) -> ActiveRuntimeLiveValues:
    return ActiveRuntimeLiveValues(
        state=cast(ResearchState, object()), context=context
    )


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


def test_model_policy_context_reads_each_rebound_context_before_sampling_time() -> None:
    calls: list[tuple[str, ...]] = []

    def check(context: dict, purpose: str) -> bool:
        calls.append(("policy", context["run"], purpose))
        context["inspected"] = True
        return context["run"] == "first"

    def now() -> str:
        calls.append(("clock",))
        return "2026-11-18T00:00:00Z"

    first: dict = {"run": "first", ACTIVE_RESEARCH_POLICY_AUDITS_KEY: []}
    second: dict = {"run": "second", ACTIVE_RESEARCH_POLICY_AUDITS_KEY: []}
    live = _live(first)
    policy = RuntimeModelPolicyContext(live=live, policy_check=check, utc_now=now)

    assert policy.allowed("research_claim_planning", ("question",))
    live.context = second
    assert not policy.allowed("research_evidence_extraction", ("source",))
    assert calls == [
        ("policy", "first", "research_claim_planning"),
        ("clock",),
        ("policy", "second", "research_evidence_extraction"),
        ("clock",),
    ]
    assert first["inspected"] is second["inspected"] is True
    assert first[ACTIVE_RESEARCH_POLICY_AUDITS_KEY][-1]["status"] == "allowed"
    assert second[ACTIVE_RESEARCH_POLICY_AUDITS_KEY][-1] == {
        "call_id": "policy:research_evidence_extraction:1",
        "purpose": "research_evidence_extraction",
        "status": "blocked_by_policy",
        "data_categories": ["source"],
        "checked_at": "2026-11-18T00:00:00Z",
    }


def test_model_policy_check_failure_writes_no_audit_or_clock_sample() -> None:
    calls: list[str] = []
    original = [{"call_id": "previous"}]
    context = {ACTIVE_RESEARCH_POLICY_AUDITS_KEY: original}

    def check(_context: dict, _purpose: str) -> bool:
        calls.append("policy")
        raise ValueError("policy unavailable")

    def now() -> str:
        calls.append("clock")
        return "never"

    with pytest.raises(ValueError, match="policy unavailable"):
        RuntimeModelPolicyContext(_live(context), check, now).allowed("planning", ())

    assert calls == ["policy"]
    assert context[ACTIVE_RESEARCH_POLICY_AUDITS_KEY] is original


def test_model_policy_clock_failure_preserves_prior_audits() -> None:
    original = [{"call_id": "previous"}]
    context = {ACTIVE_RESEARCH_POLICY_AUDITS_KEY: original}

    def clock_failure() -> str:
        raise TimeoutError("clock failed")

    with pytest.raises(TimeoutError, match="clock failed"):
        RuntimeModelPolicyContext(
            _live(context), lambda _context, _purpose: True, clock_failure
        ).allowed("planning", ())

    assert context[ACTIVE_RESEARCH_POLICY_AUDITS_KEY] is original


def test_policy_rebind_during_check_keeps_one_audit_target_and_order() -> None:
    """No split audit: callbacks cannot move a single decision across mappings."""

    first: dict = {"run": "first"}
    rebound: dict = {"run": "rebound"}
    live = _live(first)
    events: list[str] = []

    def check(context: dict, purpose: str) -> bool:
        events.append("policy")
        assert context is first
        assert purpose == "research_claim_planning"
        live.context = rebound
        return True

    def clock() -> str:
        events.append("clock")
        return "2026-11-22T00:00:00Z"

    policy = RuntimeModelPolicyContext(live, check, clock)
    assert policy.allowed("research_claim_planning", ("question",))
    assert events == ["policy", "clock"]
    assert first[ACTIVE_RESEARCH_POLICY_AUDITS_KEY][-1]["status"] == "allowed"
    assert ACTIVE_RESEARCH_POLICY_AUDITS_KEY not in rebound

    # The next call uses the new context, never a cached run-level mapping.
    live.context = rebound
    policy2 = RuntimeModelPolicyContext(
        live, lambda context, purpose: context is rebound, clock
    )
    assert policy2.allowed("research_evidence_extraction", ("source",))
    assert rebound[ACTIVE_RESEARCH_POLICY_AUDITS_KEY][-1]["purpose"] == (
        "research_evidence_extraction"
    )
