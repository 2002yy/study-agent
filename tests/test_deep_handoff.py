"""Deep-1 pure logic: the escalation rule, the handoff digest and the child identity.

The rule under test is the one that keeps Deep honest: only a Standard result that finished its
own research and still has a gap may escalate. An execution failure is never laundered into a
new research opportunity.
"""

from __future__ import annotations

import pytest

from src.web.research.deep_handoff import (
    BLOCKED,
    DEEP_HANDOFF_SCHEMA,
    DEEP_TERMINAL_SCHEMA,
    NOT_REQUESTED,
    PENDING,
    UPGRADE_STOP_REASONS,
    build_deep_handoff,
    decide_deep_handoff,
    deep_child_identity,
    deep_terminal,
    load_deep_handoff,
    payload_digest,
)

GAPPED = {"unresolved_gaps": ["release_date"], "gap_states": {}, "conflicts": []}
RESOLVED = {"unresolved_gaps": [], "gap_states": {}, "conflicts": []}


# --- D1: a fully resolved Standard does not escalate ------------------------------


def test_resolved_standard_is_not_requested():
    for reason in UPGRADE_STOP_REASONS:
        assert decide_deep_handoff(RESOLVED, stop_reason=reason) == NOT_REQUESTED


# --- D2 / D3 / D4: execution failures never escalate ------------------------------


@pytest.mark.parametrize(
    "reason", ["cancelled", "planner_invalid", "planner_failed", "result_unknown"]
)
def test_execution_failures_are_not_requested(reason):
    assert decide_deep_handoff(GAPPED, stop_reason=reason) == NOT_REQUESTED


def test_unknown_stop_reason_is_blocked():
    assert decide_deep_handoff(GAPPED, stop_reason="not_a_real_reason") == BLOCKED


def test_a_gap_after_a_normal_terminal_escalates():
    for reason in UPGRADE_STOP_REASONS:
        assert decide_deep_handoff(GAPPED, stop_reason=reason) == PENDING


# --- handoff digest ---------------------------------------------------------------


def _handoff(**overrides):
    base = dict(
        parent_turn_id="turn-1",
        query="release date of Python 3.14.0",
        standard_child_run_id="standard-abc",
        standard_source_run_id="source-run",
        standard_handoff_sha256="h" * 64,
        standard_result=GAPPED,
        seed_source_refs=[{"url": "https://x", "content_sha256": "d" * 64, "fields": [], "origin": "standard"}],
    )
    base.update(overrides)
    return build_deep_handoff(**base)


def test_handoff_carries_its_schema_and_no_authority():
    handoff = _handoff()
    assert handoff["schema_version"] == DEEP_HANDOFF_SCHEMA
    assert handoff["publication_authority"] is False
    assert handoff["budget_profile"] == "deep-v1"
    assert handoff["payload_sha256"] == payload_digest(handoff)


def test_handoff_refs_carry_no_body():
    ref = _handoff()["seed_source_refs"][0]
    assert "content" not in ref
    assert set(ref) == {"url", "content_sha256", "fields", "origin"}


def test_tampered_handoff_is_rejected():
    handoff = _handoff()
    handoff["unresolved_fields"] = ["something_else"]
    with pytest.raises(ValueError):
        load_deep_handoff(handoff)


def test_handoff_that_grants_authority_is_rejected():
    handoff = _handoff()
    handoff["publication_authority"] = True
    handoff["payload_sha256"] = payload_digest(handoff)
    with pytest.raises(ValueError):
        load_deep_handoff(handoff)


def test_well_formed_handoff_loads():
    loaded = load_deep_handoff(_handoff())
    assert loaded["schema_version"] == DEEP_HANDOFF_SCHEMA
    assert "payload_sha256" not in loaded


# --- deterministic identity -------------------------------------------------------


def test_child_identity_is_deterministic():
    first = deep_child_identity("turn-1", "standard-abc")
    second = deep_child_identity("turn-1", "standard-abc")
    assert first == second
    assert first[0].startswith("deep-") and len(first[0]) == len("deep-") + 24
    assert first[1] == "deep-handoff:turn-1:standard-abc"


def test_child_identity_differs_per_standard_child():
    assert deep_child_identity("turn-1", "a")[0] != deep_child_identity("turn-1", "b")[0]


# --- terminal namespace -----------------------------------------------------------


def test_deep_terminal_uses_its_own_schema_and_state():
    terminal = deep_terminal(
        parent_turn_id="turn-1",
        thread_id="thread-1",
        source_run_id="source-run",
        child_run_id="deep-abc",
        handoff=_handoff(),
        dispatch_status=PENDING,
    )
    assert terminal["schema_version"] == DEEP_TERMINAL_SCHEMA
    assert terminal["state"] == "ESCALATE_DEEP"
    assert terminal["dispatch_status"] == PENDING
    assert terminal["child_run_id"] == "deep-abc"
    assert terminal["owner"] == {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "run_id": "source-run",
    }


def test_blocked_terminal_carries_a_bounded_reason():
    terminal = deep_terminal(
        parent_turn_id="turn-1",
        thread_id="thread-1",
        source_run_id="",
        child_run_id="",
        handoff={},
        dispatch_status=BLOCKED,
        reason="handoff_integrity_failure",
    )
    assert terminal["dispatch_status"] == BLOCKED
    assert terminal["reason"] == "handoff_integrity_failure"
    assert "child_run_id" not in terminal
