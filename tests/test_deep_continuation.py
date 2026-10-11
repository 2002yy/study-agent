"""Deep-3: continue a pending Deep handoff and project the child terminal to the parent.

The controls that matter: a terminal child is never re-executed, an honest research terminal
maps to a completed parent while only deterministic integrity becomes blocked, the projection
carries control-plane facts only, and nothing here touches the answer, pedagogy or learning
state.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.application.deep_continuation import DeepContinuationService
from src.application.deep_execution import DeepExecutionService
from src.application.deep_handoff import DeepHandoffService
from src.application.standard_continuation import StandardContinuationService
from src.repositories.deep_continuation_repository import (
    DeepFinalizationError,
    child_terminal_digest,
)
from src.web.research.standard_plan import PLAN_SCHEMA
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent


class CountingExecution:
    """Stands in for DeepExecutionService so a test can assert it was never called."""

    def __init__(self, outcome=None):
        self.calls = 0
        self._outcome = outcome

    def execute(self, *, parent_turn_id, thread_id):
        self.calls += 1
        return self._outcome


class Outcome:
    def __init__(self, status, reason=""):
        self.status = status
        self.reason = reason


def planner(request):
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


class _NeverDispatch:
    """Admission only: the real envelope is attached, no research is dispatched."""

    def execute(self, run_id):
        return None


@pytest.fixture
def ctx(saved_parent):
    """A parent with a completed Standard artifact and a prepared Deep child."""

    repository, runs, parent, created = saved_parent
    gateway = Gateway()
    clock = [created + timedelta(seconds=3)]
    StandardContinuationService(
        repository, runs, gateway, clock=lambda: clock[0], planner_factory=lambda: planner
    ).continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    prepared = DeepHandoffService(repository, runs).prepare(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    assert prepared.status == "prepared"

    # Run the real Deep-2 admission so the child carries the execution envelope and the active
    # state a terminal child would always have in production.
    DeepExecutionService(repository, runs, _NeverDispatch()).execute(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )

    execution = CountingExecution()
    service = DeepContinuationService(repository, runs, execution)  # type: ignore[arg-type]
    return service, repository, runs, parent, prepared, execution


def snapshot(repository, parent):
    return repository.get_chat_turn(parent.id).rag_snapshot


def tamper(repository, parent, mutate):
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    mutate(snap)
    repository.update_chat_turn(
        turn.id,
        assistant_message=turn.assistant_message,
        status=turn.status,
        rag_snapshot=snap,
    )


def set_child_status(repository, child_run_id, status):
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET status = ?, stop_reason = ?, provider_status = ? "
            "WHERE id = ?",
            (status, f"stop_{status}", "found", child_run_id),
        )


# --- F1 / F2 / F3 / F4: terminal authority ----------------------------------------


def test_f1_no_deep_terminal_is_not_requested(ctx):
    service, repository, _runs, parent, _prepared, execution = ctx
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap.pop("deep_terminal", None)
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status, rag_snapshot=snap
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "not_requested"
    assert execution.calls == 0


def test_f4_a_malformed_recorded_terminal_fails_closed_without_rewriting(ctx):
    service, repository, _runs, parent, _prepared, execution = ctx
    tamper(repository, parent, lambda snap: snap.__setitem__("deep_terminal", None))
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert execution.calls == 0
    # The recorded value is left exactly as it was.
    assert snapshot(repository, parent)["deep_terminal"] is None


# --- F5 / F6: lineage -------------------------------------------------------------


def test_f5_a_missing_child_is_blocked(ctx):
    service, repository, _runs, parent, _prepared, execution = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"].__setitem__("child_run_id", "deep-missing"),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert execution.calls == 0
    # Durable, not merely returned: the parent terminal really moved to blocked.
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "blocked"


def test_f6_a_lineage_mismatch_is_blocked(ctx):
    service, repository, runs, parent, prepared, execution = ctx
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET parent_run_id = ? WHERE id = ?",
            ("not-the-standard-child", prepared.child_run_id),
        )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert execution.calls == 0
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "blocked"


def test_a_wrong_thread_is_blocked(ctx):
    service, _repository, _runs, parent, _prepared, execution = ctx
    result = service.continue_pending(parent_turn_id=parent.id, thread_id="other")
    assert result.status == "blocked"
    assert execution.calls == 0


# --- F7 / F8 / F9 / F10: terminal child never re-executes --------------------------


@pytest.mark.parametrize("child_status", ["completed", "partial", "failed", "cancelled"])
def test_f7_to_f10_a_terminal_child_is_finalized_not_executed(ctx, child_status):
    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, child_status)

    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)

    assert result.status == "completed"
    assert execution.calls == 0
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["dispatch_status"] == "completed"
    assert terminal["result"]["child_status"] == child_status
    assert terminal["result"]["publication_authority"] is False


def test_f20_the_projection_carries_control_plane_facts_only(ctx):
    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    result = snapshot(repository, parent)["deep_terminal"]["result"]
    assert set(result) == {
        "schema_version",
        "child_run_id",
        "child_status",
        "provider_status",
        "stop_reason",
        "answer_confidence",
        "completed_at",
        "handoff_sha256",
        "child_terminal_sha256",
        "publication_authority",
    }
    assert result["schema_version"] == "deep-auto-continuation-v1"
    # No evidence, no bodies, no cursor.
    for forbidden in ("selected_sources", "research_context", "items", "evidence", "seed"):
        assert forbidden not in result


def test_the_child_terminal_digest_is_stable(ctx):
    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    first = snapshot(repository, parent)["deep_terminal"]["result"]["child_terminal_sha256"]
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = snapshot(repository, parent)["deep_terminal"]["result"]["child_terminal_sha256"]
    assert first == second
    assert first


# --- F13 / F15 / F16: execution outcomes ------------------------------------------


def test_f13_a_deferred_execution_leaves_the_parent_pending(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    execution._outcome = Outcome("deferred", "lease_busy")
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "deferred"
    assert execution.calls == 1
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "pending"


def test_f15_a_blocked_execution_blocks_the_parent(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    execution._outcome = Outcome("blocked", "seed_integrity_failure")
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["dispatch_status"] == "blocked"
    assert terminal["reason"] == "seed_integrity_failure"


def test_f16_an_unknown_execution_error_propagates_and_leaves_the_parent_pending(ctx):
    service, repository, _runs, parent, prepared, execution = ctx

    class Exploding:
        def execute(self, **_kwargs):
            raise RuntimeError("provider exploded")

    service.execution = Exploding()  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "pending"


def test_a_completed_execution_finalizes_only_after_reloading_the_child(ctx):
    service, repository, runs, parent, prepared, execution = ctx

    class Completing:
        def execute(self, *, parent_turn_id, thread_id):
            # The child really reaches a terminal before the outcome is returned.
            set_child_status(repository, prepared.child_run_id, "completed")
            return Outcome("completed")

    service.execution = Completing()  # type: ignore[assignment]
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "completed"
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "completed"


def test_an_outcome_claiming_completion_without_a_terminal_child_stays_pending(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    execution._outcome = Outcome("completed")
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "deferred"
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "pending"


# --- F17 / F18 / F19: tamper between child terminal and finalize -------------------


def test_f17_a_tampered_seed_blocks_finalization(ctx):
    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        context["deep"]["seed"]["sources"][0]["content"] = "tampered"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "seed_integrity_failure"
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "blocked"


def test_f18_a_tampered_envelope_blocks_finalization(ctx):
    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        context["deep"]["execution"]["handoff_sha256"] = "f" * 64
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "execution_envelope_invalid"
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "blocked"


def test_f19_a_changed_handoff_blocks_finalization(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["handoff"].__setitem__("unresolved_fields", ["x"]),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "handoff_integrity_failure"
    assert snapshot(repository, parent)["deep_terminal"]["dispatch_status"] == "blocked"


# --- F22 / F23 / F25: crash and race windows --------------------------------------


def test_f22_a_crash_after_the_child_terminal_finalizes_without_rerunning(ctx):
    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    # A fresh service stands in for a restarted process: only durable truth is available.
    fresh = DeepContinuationService(repository, runs, execution)  # type: ignore[arg-type]
    result = fresh.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "completed"
    assert execution.calls == 0


def test_f23_a_lost_result_returns_the_same_terminal(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    first = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.status == second.status == "completed"
    assert first.result == second.result
    assert execution.calls == 0


def test_f25_first_terminal_wins(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    # A later block attempt must not flip a completed terminal.
    terminal = service.terminal.block(
        parent_turn_id=parent.id, thread_id=parent.thread_id, reason="late_failure"
    )
    assert terminal["dispatch_status"] == "completed"


# --- F26 / F27 / F28: nothing else moves ------------------------------------------


def test_f26_to_f28_the_parent_keeps_everything_else(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    before = snapshot(repository, parent)
    message = repository.get_chat_turn(parent.id).assistant_message
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    after = snapshot(repository, parent)
    assert repository.get_chat_turn(parent.id).assistant_message == message
    assert after["lookup_terminal"] == before["lookup_terminal"]
    assert after["standard_continuation"] == before["standard_continuation"]
    assert set(after) == set(before)


def test_f21_publication_authority_is_false_everywhere(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["result"]["publication_authority"] is False


def test_the_repository_raises_a_bounded_reason(ctx):
    _service, repository, _runs, parent, prepared, _execution = ctx
    from src.repositories.deep_continuation_repository import DeepContinuationRepository

    repo = DeepContinuationRepository(repository.database)
    with pytest.raises(DeepFinalizationError) as exc:
        repo.finalize(
            parent_turn_id=parent.id,
            thread_id=parent.thread_id,
            expected_child_run_id="deep-not-the-child",
        )
    assert exc.value.reason
    assert " " not in exc.value.reason


def test_child_terminal_digest_is_a_pure_projection():
    class Child:
        id = "c"
        status = "completed"
        provider_status = "found"
        stop_reason = "ready_for_binding"
        answer_confidence = "high"
        completed_at = "2026-10-07T00:00:00+00:00"

    digest = child_terminal_digest(Child())
    assert digest == child_terminal_digest(Child())
    assert len(digest) == 64


def test_f35_seed_refs_that_disagree_with_the_handoff_block_finalization(ctx):
    """Only the handoff-vs-seed refs check can catch this: refs and sources agree."""

    service, repository, runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        seed = context["deep"]["seed"]
        # Both sides move together, so the projection stays consistent; only the
        # comparison against the handoff can reject it.
        for side in ("sources", "refs"):
            seed[side][0]["url"] = "https://evil.example/x"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "seed_integrity_failure"


# --- review round 1: existing-terminal integrity and transaction ordering ----------


def test_a_valid_completed_terminal_is_returned_unchanged(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    first = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.status == second.status == "completed"
    assert first.result == second.result
    assert execution.calls == 0


def test_a_completed_terminal_without_a_result_is_not_trusted(ctx):
    service, repository, _runs, parent, _prepared, execution = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"].update(
            {"dispatch_status": "completed", "result": None}
        ),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"
    assert execution.calls == 0


def test_a_completed_terminal_that_can_publish_is_not_trusted(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)

    def mutate(snap):
        snap["deep_terminal"]["result"]["publication_authority"] = True

    tamper(repository, parent, mutate)
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"


def test_a_blocked_terminal_with_a_raw_reason_is_not_trusted(ctx):
    service, repository, _runs, parent, _prepared, execution = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"].update(
            {"dispatch_status": "blocked", "reason": "Traceback (most recent call last)"}
        ),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"


def test_first_terminal_wins_before_positive_validation(ctx):
    """A settled parent must not be re-examined against a child that has since broken."""

    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    settled = snapshot(repository, parent)["deep_terminal"]["result"]["child_terminal_sha256"]

    # Damage the child after the parent settled.
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        context["deep"]["seed"]["sources"][0]["content"] = "damaged after settle"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )

    # Both transitions must return the settled terminal without touching the child.
    finalized = service.terminal.finalize(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        expected_child_run_id=prepared.child_run_id,
    )
    assert finalized["dispatch_status"] == "completed"
    assert finalized["result"]["child_terminal_sha256"] == settled
    blocked = service.terminal.block(
        parent_turn_id=parent.id, thread_id=parent.thread_id, reason="late_failure"
    )
    assert blocked["dispatch_status"] == "completed"


def test_a_blocked_reason_is_bounded(ctx):
    _service, repository, _runs, parent, _prepared, _execution = ctx
    from src.repositories.deep_continuation_repository import DeepContinuationRepository

    repo = DeepContinuationRepository(repository.database)
    terminal = repo.block(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        reason="Traceback: KeyError(\"secret\")",
    )
    assert terminal["reason"] == "admission_failed"


# --- review round 2: owner binding and exact result shape --------------------------


def test_a_pending_terminal_with_a_wrong_owner_is_durably_blocked(ctx):
    """A corrupted owner is the failure to record, not a reason the block cannot persist."""

    service, repository, _runs, parent, _prepared, execution = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["owner"].__setitem__("thread_id", "other"),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["dispatch_status"] == "blocked"
    assert terminal["reason"] == "terminal_integrity_failure"
    assert execution.calls == 0


def _completed_terminal(ctx):
    service, repository, _runs, parent, prepared, execution = ctx
    set_child_status(repository, prepared.child_run_id, "completed")
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    return service, repository, parent, execution


def test_a_completed_terminal_with_a_wrong_owner_is_not_trusted(ctx):
    service, repository, parent, execution = _completed_terminal(ctx)
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["owner"].__setitem__("thread_id", "other"),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"


def test_a_completed_terminal_missing_a_result_field_is_not_trusted(ctx):
    service, repository, parent, execution = _completed_terminal(ctx)
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["result"].pop("child_terminal_sha256"),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"


def test_a_completed_terminal_with_an_injected_field_is_not_trusted(ctx):
    service, repository, parent, execution = _completed_terminal(ctx)
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["result"].__setitem__("raw_body", "x"),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"


def test_a_completed_terminal_with_a_tampered_handoff_is_not_trusted(ctx):
    service, repository, parent, execution = _completed_terminal(ctx)
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["handoff"].__setitem__(
            "unresolved_fields", ["x"]
        ),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"


def test_a_blocked_terminal_with_an_injected_result_is_not_trusted(ctx):
    service, repository, _runs, parent, _prepared, execution = ctx
    service.terminal.block(
        parent_turn_id=parent.id, thread_id=parent.thread_id, reason="lineage_mismatch"
    )
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"].__setitem__("result", {"raw_body": "x"}),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "terminal_integrity_failure"
    assert result.result is None


# --- review round 3: a legitimate blocked terminal must stay readable -----------------


def test_a_deep1_shaped_blocked_terminal_is_returned_as_blocked(ctx):
    """Deep-1 records a blocked terminal with no handoff and no child."""

    service, repository, _runs, parent, _prepared, execution = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap.__setitem__(
            "deep_terminal",
            {
                "schema_version": "standard-deep-terminal-v1",
                "state": "ESCALATE_DEEP",
                "reason": "standard_artifact_invalid",
                "dispatch_status": "blocked",
                "owner": {"thread_id": parent.thread_id, "turn_id": parent.id},
                "handoff": {},
            },
        ),
    )
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "standard_artifact_invalid"
    assert execution.calls == 0
    # Returned as recorded: nothing rewritten.
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["dispatch_status"] == "blocked"
    assert terminal["reason"] == "standard_artifact_invalid"
    assert terminal["handoff"] == {}


def test_a_blocked_terminal_keeps_its_own_reason_across_reads(ctx):
    """The corruption that caused a block must not invalidate the block itself."""

    service, repository, _runs, parent, _prepared, execution = ctx
    # Damage the pending handoff, so the first continuation blocks on it.
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["handoff"].__setitem__("payload_sha256", ""),
    )
    first = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.status == "blocked"
    assert first.reason == "handoff_integrity_failure"
    durable = snapshot(repository, parent)["deep_terminal"]
    assert durable["dispatch_status"] == "blocked"
    assert durable["reason"] == "handoff_integrity_failure"

    # A second read must not re-derive a different reason from the damaged handoff.
    second = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "blocked"
    assert second.reason == "handoff_integrity_failure"
    assert execution.calls == 0


def test_upstream_blocked_reasons_are_accepted(ctx):
    from src.repositories.deep_continuation_repository import validate_recorded_terminal

    _service, _repository, _runs, parent, _prepared, _execution = ctx
    for reason in (
        "standard_artifact_invalid",
        "owner_mismatch",
        "journal_invalid",
        "seed_integrity_failure",
    ):
        terminal = {
            "schema_version": "standard-deep-terminal-v1",
            "state": "ESCALATE_DEEP",
            "dispatch_status": "blocked",
            "reason": reason,
            "owner": {"thread_id": parent.thread_id, "turn_id": parent.id},
            "handoff": {},
        }
        assert validate_recorded_terminal(
            terminal, parent_turn_id=parent.id, thread_id=parent.thread_id
        ) == (True, "")


# --- M4-B real-path pairing: the Deep shadow observes only a genuinely-reached terminal ------


def _spy_shadow(monkeypatch, service):
    seen: list[str] = []
    monkeypatch.setattr(
        service, "_observe_deep_shadow", lambda *, query, handoff: seen.append(query)
    )
    return seen


def test_shadow_fires_once_only_for_a_newly_terminal_child(ctx, monkeypatch):
    service, repository, _runs, parent, prepared, _execution = ctx
    monkeypatch.setenv("BSEARCH_DEEP_SHADOW", "on")
    seen = _spy_shadow(monkeypatch, service)

    class _Exec:
        def execute(self, *, parent_turn_id, thread_id):
            set_child_status(repository, prepared.child_run_id, "completed")
            return Outcome("completed")

    service.execution = _Exec()
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "completed"
    assert len(seen) == 1  # observed exactly once, for the terminal this run reached


def test_shadow_never_fires_for_a_replayed_terminal(ctx, monkeypatch):
    service, repository, _runs, parent, prepared, _execution = ctx
    monkeypatch.setenv("BSEARCH_DEEP_SHADOW", "on")
    seen = _spy_shadow(monkeypatch, service)

    set_child_status(repository, prepared.child_run_id, "completed")
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "completed"
    assert seen == []  # a resumption/replay must not double-count the phase


def test_shadow_never_fires_for_a_deferred_child(ctx, monkeypatch):
    service, _repository, _runs, parent, _prepared, _execution = ctx
    monkeypatch.setenv("BSEARCH_DEEP_SHADOW", "on")
    seen = _spy_shadow(monkeypatch, service)

    class _Exec:
        def execute(self, *, parent_turn_id, thread_id):
            return Outcome("deferred", "lease_busy")

    service.execution = _Exec()
    result = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "deferred"
    assert seen == []  # a non-terminal run is not recorded as "observed after completion"


def test_shadow_helper_is_inert_when_disabled(ctx, monkeypatch):
    service, _repository, _runs, parent, _prepared, _execution = ctx
    monkeypatch.delenv("BSEARCH_DEEP_SHADOW", raising=False)
    assert service.shadow_telemetry is None  # OFF provisions nothing
