"""Deep-1 integration: prepare a Deep handoff from a completed Standard artifact.

The controls that matter here: Deep only starts from a completed Standard terminal with a real
gap; it never rewrites Standard's artifact or the assistant message; it runs no network and no
model; the child is deterministic; and the seed holds already-read bytes rather than being
re-fetched later.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.application.deep_handoff import DeepHandoffService
from src.application.standard_continuation import StandardContinuationService
from src.repositories.standard_execution_repository import StandardExecutionRepository
from src.web.research.standard_plan import PLAN_SCHEMA
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent


def planner(request):
    # A valid plan must cover every unresolved field; an empty gap list is rejected.
    handoff = request["handoff"]
    return {
        "schema": PLAN_SCHEMA,
        "query": handoff["query"],
        "handoff_sha256": handoff["payload_sha256"],
        "gaps": [
            {"field": field, "queries": [], "candidate_urls": []}
            for field in handoff["unresolved_fields"]
        ],
    }


@pytest.fixture
def ctx(saved_parent):
    """A parent whose Standard continuation has completed and left a gap."""

    repository, runs, parent, created = saved_parent
    gateway = Gateway()
    clock = [created + timedelta(seconds=3)]
    continuation = StandardContinuationService(
        repository,
        runs,
        gateway,
        clock=lambda: clock[0],
        planner_factory=lambda: planner,
    )
    outcome = continuation.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    assert outcome.status == "completed"
    assert outcome.result["unresolved_gaps"], "fixture needs a Standard gap to escalate"

    service = DeepHandoffService(repository, runs)
    return service, repository, runs, parent, gateway, clock, outcome


def snapshot(repository, parent):
    return repository.get_chat_turn(parent.id).rag_snapshot


def tamper(repository, parent, mutate):
    """Rewrite the parent snapshot in place, keeping the other required fields."""

    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    mutate(snap)
    repository.update_chat_turn(
        turn.id,
        assistant_message=turn.assistant_message,
        status=turn.status,
        rag_snapshot=snap,
    )


# --- happy path -------------------------------------------------------------------


def test_a_gapped_standard_artifact_prepares_a_deep_child(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "prepared"
    assert result.child_run_id.startswith("deep-")
    assert result.handoff_sha256
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["state"] == "ESCALATE_DEEP"
    assert terminal["dispatch_status"] == "pending"
    assert terminal["child_run_id"] == result.child_run_id


# --- D21 / D22: lineage and identity ---------------------------------------------


def test_deep_child_lineage_and_query(ctx):
    service, repository, runs, parent, _gateway, _clock, outcome = ctx
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    child = runs.get(result.child_run_id)
    assert child.parent_run_id == outcome.child_run_id  # the Standard child
    assert child.query == parent.user_message
    assert child.owner_thread_id == parent.thread_id


# --- D11 / D12: exactly-once ------------------------------------------------------


def test_duplicate_prepare_returns_the_same_child(ctx):
    service, repository, runs, parent, _gateway, _clock, _outcome = ctx
    first = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.child_run_id == first.child_run_id
    assert second.status == "prepared"


def test_duplicate_prepare_does_not_duplicate_the_seed(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    seed = service.deep_seed(
        snapshot(repository, parent)["deep_terminal"]["child_run_id"], parent.thread_id
    )
    urls = [source["url"] for source in seed["sources"]]
    assert len(urls) == len(set(urls))


# --- D13: no body in the parent snapshot -----------------------------------------


def test_the_parent_snapshot_carries_no_body(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    raw = json.dumps(snapshot(repository, parent))
    assert "was released on" not in raw
    assert "new body" not in raw


def test_handoff_refs_hold_no_content(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    refs = snapshot(repository, parent)["deep_terminal"]["handoff"]["seed_source_refs"]
    for ref in refs:
        assert "content" not in ref


# --- D15: no publication authority ------------------------------------------------


def test_no_path_grants_publication_authority(ctx):
    service, repository, runs, parent, _gateway, _clock, _outcome = ctx
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["handoff"]["publication_authority"] is False
    seed = service.deep_seed(result.child_run_id, parent.thread_id)
    assert "publication_authority" not in seed


# --- D16 / D17: nothing else moves ------------------------------------------------


def test_standard_artifacts_are_unchanged(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    before = snapshot(repository, parent)
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    after = snapshot(repository, parent)
    assert after["lookup_terminal"] == before["lookup_terminal"]
    assert after["standard_continuation"] == before["standard_continuation"]
    assert set(after) - set(before) == {"deep_terminal"}


def test_assistant_message_is_unchanged(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    before = repository.get_chat_turn(parent.id).assistant_message
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert repository.get_chat_turn(parent.id).assistant_message == before


# --- D18 / D19 / D20: inert -------------------------------------------------------


def test_prepare_makes_no_gateway_calls(ctx):
    service, repository, _runs, parent, gateway, _clock, _outcome = ctx
    before = gateway.reads + gateway.queries
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert gateway.reads + gateway.queries == before


def test_prepare_attaches_no_active_claim_engine_state(ctx):
    service, repository, runs, parent, _gateway, _clock, _outcome = ctx
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    child = runs.get(result.child_run_id)
    assert child.status == "pending"
    context = child.research_context
    # The child carries a seed and nothing that would look like an active research session.
    assert "deep" in context
    assert "claim_engine" not in context
    assert "runtime" not in context
    assert "research_state" not in context


# --- D10: wrong thread ------------------------------------------------------------


def test_wrong_thread_is_blocked(ctx):
    service, _repository, _runs, parent, _gateway, _clock, _outcome = ctx
    result = service.prepare(parent_turn_id=parent.id, thread_id="some-other-thread")
    assert result.status == "blocked"
    assert result.reason == "owner_mismatch"


# --- D5: a blocked Standard continuation never escalates --------------------------


def test_blocked_standard_continuation_is_not_requested(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    tamper(repository, parent, lambda snap: snap["lookup_terminal"].__setitem__("dispatch_status", "blocked"))
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "not_requested"
    assert "deep_terminal" not in snapshot(repository, parent)


# --- D6: tampered Standard handoff digest ----------------------------------------


def test_tampered_standard_continuation_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    tamper(repository, parent, lambda snap: snap["standard_continuation"].__setitem__("handoff_sha256", "f" * 64))
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


# --- D7 / D8: lineage mismatch ----------------------------------------------------


def test_a_missing_standard_child_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    tamper(repository, parent, lambda snap: snap["standard_continuation"].__setitem__("child_run_id", "standard-does-not-exist"))
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


def test_a_source_run_mismatch_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    tamper(repository, parent, lambda snap: snap["standard_continuation"].__setitem__("source_run_id", "not-the-source"))
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


# --- a missing parent -------------------------------------------------------------


def test_a_missing_parent_is_blocked(ctx):
    service, _repository, _runs, _parent, _gateway, _clock, _outcome = ctx
    result = service.prepare(parent_turn_id="missing-turn", thread_id="whatever")
    assert result.status == "blocked"


# --- the ledger read is owner-checked --------------------------------------------


def test_standard_ledger_read_rejects_a_foreign_thread(ctx):
    service, repository, _runs, parent, _gateway, _clock, outcome = ctx
    journal = StandardExecutionRepository(repository.database)
    with pytest.raises(ValueError):
        journal.child_ledger(outcome.child_run_id, "some-other-thread")
