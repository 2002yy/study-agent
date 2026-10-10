"""Standard-4 continuation: order, exactly-once, no clock restart, and a safe answer.

The controls that matter: admission happens only after the parent is durably completed; the
parent stays pending while the child works; a second call returns the same child without
re-planning; the deadline is derived from the parent and never restarted; and no path grants
publication authority or touches the assistant message.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.application.standard_continuation import (
    StandardContinuationService,
    blocked_reason,
    derive_target,
)
from src.application.standard_execution import StandardExecution
from src.repositories.standard_execution_repository import StandardExecutionRepository
from src.web.research.standard_plan import PLAN_SCHEMA
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent


def planner(request):
    handoff = request["handoff"]
    return {
        "schema": PLAN_SCHEMA,
        "query": handoff["query"],
        "handoff_sha256": handoff["payload_sha256"],
        "gaps": [],
    }


@pytest.fixture
def ctx(saved_parent):
    repository, runs, parent, created = saved_parent
    gateway = Gateway()
    clock = [created + timedelta(seconds=3)]
    service = StandardContinuationService(
        repository,
        runs,
        gateway,
        clock=lambda: clock[0],
        planner_factory=lambda: planner,
    )
    return service, repository, runs, parent, created, gateway, clock


def snapshot(repository, parent):
    return repository.get_chat_turn(parent.id).rag_snapshot


# --- G1: admission only after the parent is durable -------------------------------


def test_continuation_completes_a_pending_handoff(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    outcome = service.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    assert outcome.status == "completed"
    assert outcome.child_run_id
    assert outcome.result is not None
    assert outcome.result["publication_authority"] is False


def test_parent_reaches_completed_with_a_durable_artifact(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    snap = snapshot(repository, parent)
    assert snap["lookup_terminal"]["dispatch_status"] == "completed"
    artifact = snap["standard_continuation"]
    assert artifact["schema_version"] == "standard-auto-continuation-v1"
    assert artifact["publication_authority"] is False
    assert artifact["handoff_sha256"]
    assert artifact["source_run_id"]


# --- G2: the parent stays pending while the child works ---------------------------


def test_parent_stays_pending_while_the_child_works(ctx):
    service, repository, runs, parent, created, _gateway, _clock = ctx
    clock = [created + timedelta(seconds=3)]
    execution = StandardExecution.start(
        repository,
        runs,
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        overall_deadline=created + timedelta(seconds=90),
        clock=lambda: clock[0],
    )
    # The journal only accepts a transaction while dispatch_status is still pending.
    journal = StandardExecutionRepository(repository.database)
    journal.check(execution.run_id, parent.thread_id, execution.operation_id, clock[0])
    assert snapshot(repository, parent)["lookup_terminal"]["dispatch_status"] == "pending"


# --- G3 / N7 / N8: exactly-once ---------------------------------------------------


def test_second_call_returns_the_same_child_without_researching(ctx):
    service, repository, _runs, parent, _created, gateway, _clock = ctx
    first = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    reads_after_first = gateway.reads + gateway.queries
    second = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.child_run_id == first.child_run_id
    assert second.status == "completed"
    assert gateway.reads + gateway.queries == reads_after_first


def test_second_call_does_not_run_the_planner_again(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    calls = []

    def counting_planner(request):
        calls.append(1)
        return planner(request)

    service.planner_factory = lambda: counting_planner
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    after_first = len(calls)
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert len(calls) == after_first


# --- G4: the clock is never restarted ---------------------------------------------


def test_deadline_is_derived_from_the_parent_creation_time(ctx):
    service, _repository, runs, parent, created, _gateway, _clock = ctx
    # Starting Standard after the original window is refused, not granted a fresh one.
    late = created + timedelta(seconds=120)
    with pytest.raises(ValueError):
        StandardExecution.start(
            service.repository,
            runs,
            parent_turn_id=parent.id,
            thread_id=parent.thread_id,
            overall_deadline=late + timedelta(seconds=90),
            clock=lambda: late,
        )


# --- N1 / N2: nothing to do --------------------------------------------------------


def test_a_parent_without_a_pending_handoff_is_not_requested(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    # No terminal at all: the continuation must decline rather than invent work.
    assert service.continue_pending(
        parent_turn_id="missing-turn", thread_id=parent.thread_id
    ).status == "blocked"


def test_second_call_after_completion_reports_completed(ctx):
    service, _repository, _runs, parent, _created, _gateway, _clock = ctx
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    outcome = service.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    assert outcome.status == "completed"
    assert outcome.reason in {"", "plan_exhausted", "ready_for_binding"}


# --- G5 / G6 / G10: binding sources and authority ----------------------------------


def test_binding_cannot_manufacture_support_from_an_unrelated_body(ctx):
    service, _repository, _runs, parent, _created, _gateway, _clock = ctx
    outcome = service.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    result = outcome.result
    assert result["publication_authority"] is False
    for state in result["gap_states"].values():
        assert state["support_status"] != "SUPPORT"
        assert state["support_status"] != "SUPPORTED"


def test_unresolved_gaps_survive_when_nothing_is_supported(ctx):
    service, _repository, _runs, parent, _created, _gateway, _clock = ctx
    outcome = service.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    result = outcome.result
    for field, state in result["gap_states"].items():
        if state["support_status"] != "SUPPORT":
            assert field in result["unresolved_gaps"]


# --- G11 / G13: the answer is untouched and a failure is safe ---------------------


def test_assistant_message_is_unchanged(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    before = repository.get_chat_turn(parent.id).assistant_message
    service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert repository.get_chat_turn(parent.id).assistant_message == before


def test_a_crashing_continuation_does_not_break_the_answer(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    before = repository.get_chat_turn(parent.id)

    class Exploding:
        repository = None

        def continue_pending(self, **_kwargs):
            raise RuntimeError("boom")

    from src.application.standard_chat_service import StandardContinuationChatService

    chat = StandardContinuationChatService.__new__(StandardContinuationChatService)
    chat._standard_continuation = Exploding()
    assert chat._refreshed(before) is before


# --- bounded reason codes ----------------------------------------------------------


def test_blocked_reason_is_bounded():
    assert blocked_reason(ValueError("Standard handoff changed")) == (
        "handoff_integrity_failure"
    )
    assert blocked_reason(ValueError("Standard source changed")) == "source_run_mismatch"
    assert blocked_reason(ValueError("Standard run owner mismatch")) == "owner_mismatch"
    assert blocked_reason(ValueError("something else")) == "admission_failed"


def test_derive_target_requires_a_unique_target():
    assert derive_target("release date of Python 3.14.0") == ("Python", "3.14.0")
    assert derive_target("compare Python 3.13 and 3.14") is None
    assert derive_target("hello") is None


def test_blocked_parent_is_recorded_without_authority(ctx):
    service, repository, _runs, parent, _created, _gateway, _clock = ctx
    service._blocked(parent.id, parent.thread_id, "handoff_integrity_failure")
    snap = snapshot(repository, parent)
    assert snap["lookup_terminal"]["dispatch_status"] == "blocked"
    assert snap["standard_continuation"]["reason"] == "handoff_integrity_failure"
    assert snap["standard_continuation"]["publication_authority"] is False


def test_datetime_is_aware(ctx):
    _service, _repository, _runs, _parent, created, _gateway, _clock = ctx
    assert isinstance(created, datetime)
    assert created.tzinfo is not None


# --- blocker: a live lease is contention, not an integrity failure ----------------


def test_a_live_lease_defers_instead_of_blocking(ctx):
    service, repository, runs, parent, created, gateway, clock = ctx
    # Another owner holds a live lease on the child.
    StandardExecution.start(
        repository,
        runs,
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        overall_deadline=created + timedelta(seconds=90),
        clock=lambda: clock[0],
    )
    before = gateway.reads + gateway.queries

    outcome = service.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )

    assert outcome.status == "deferred"
    assert outcome.reason == "lease_busy"
    snap = snapshot(repository, parent)
    assert snap["lookup_terminal"]["dispatch_status"] == "pending"
    assert "standard_continuation" not in snap
    assert gateway.reads + gateway.queries == before


def test_lease_contention_is_a_value_error_subclass(ctx):
    from src.repositories.standard_execution_repository import StandardResearchBusy

    assert issubclass(StandardResearchBusy, ValueError)


# --- G13: complete_turn really swallows a continuation failure --------------------


def _chat_with(continuation):
    from src.application.standard_chat_service import StandardContinuationChatService

    chat = StandardContinuationChatService.__new__(StandardContinuationChatService)
    chat._standard_continuation = continuation
    return chat


def test_complete_turn_swallows_a_continuation_failure(ctx, monkeypatch):
    from src.application import policy_chat_service as pcs

    _service, repository, _runs, parent, _created, _gateway, _clock = ctx
    completed = repository.get_chat_turn(parent.id)
    before = completed.assistant_message
    monkeypatch.setattr(
        pcs.ExternalDataPolicyChatService,
        "complete_turn",
        lambda self, prepared, suffix: completed,
    )

    class Exploding:
        repository = None

        def continue_pending(self, **_kwargs):
            raise RuntimeError("boom")

    result = _chat_with(Exploding()).complete_turn(prepared=None, suffix="")
    assert result is completed
    assert result.assistant_message == before


def test_complete_turn_returns_the_refreshed_turn_when_continuation_fails(ctx, monkeypatch):
    from src.application import policy_chat_service as pcs

    _service, repository, _runs, parent, _created, _gateway, _clock = ctx
    completed = repository.get_chat_turn(parent.id)
    before = completed.assistant_message
    monkeypatch.setattr(
        pcs.ExternalDataPolicyChatService,
        "complete_turn",
        lambda self, prepared, suffix: completed,
    )

    class ExplodingWithRepo:
        def __init__(self, repo):
            self.repository = repo

        def continue_pending(self, **_kwargs):
            raise RuntimeError("boom")

    result = _chat_with(ExplodingWithRepo(repository)).complete_turn(
        prepared=None, suffix=""
    )
    assert result is not None
    assert result.assistant_message == before


def test_complete_turn_is_a_no_op_without_a_continuation_service(ctx, monkeypatch):
    from src.application import policy_chat_service as pcs

    _service, repository, _runs, parent, _created, _gateway, _clock = ctx
    completed = repository.get_chat_turn(parent.id)
    monkeypatch.setattr(
        pcs.ExternalDataPolicyChatService,
        "complete_turn",
        lambda self, prepared, suffix: completed,
    )
    assert _chat_with(None).complete_turn(prepared=None, suffix="") is completed


def test_shadow_on_records_a_non_authoritative_observation_on_the_real_path(
    ctx, tmp_path, monkeypatch
):
    """M4-A acceptance: on the REAL continuation path, flag ON must leave the Standard
    outcome intact and actually persist a non-authoritative observation.

    The OFF baseline is the whole existing continuation suite (it runs with the flag
    unset); here we additionally pin that OFF provisions no sink and ON does.
    """
    import json
    import time

    from src.application.standard_shadow_seam import grants_evidence_authority

    log = tmp_path / "shadow" / "observations.jsonl"
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW", "on")
    monkeypatch.setenv("BSEARCH_STANDARD_SHADOW_LOG", str(log))

    _off_service, repository, runs, parent, _created, gateway, clock = ctx
    # built before the flag was set -> no sink, no work
    assert _off_service.shadow_telemetry is None

    service = StandardContinuationService(
        repository, runs, gateway, clock=lambda: clock[0], planner_factory=lambda: planner
    )
    assert service.shadow_telemetry is not None
    # hermetic: never run the real observer inside CI
    service.shadow_runner = lambda q, b: {
        "stop_reason": "finished",
        "authoritative": True,
        "evidence_completion": "SUPPORTED",
    }

    outcome = service.continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "completed"
    assert outcome.result is not None

    assert service.shadow_telemetry.flush(timeout=2.0) is True
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not log.exists():
        time.sleep(0.01)
    record = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert record["authoritative"] is False
    assert record["observation"]["evidence_completion"] == "UNVERIFIED"
    assert grants_evidence_authority(record) is False
