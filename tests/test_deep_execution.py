"""Deep-2: admission, atomic attach, and the fail-closed rules around the Claim Engine.

The controls that matter: Deep never trusts the Deep-1 artifact, absent and unusable Claim
Engine states are separated so an invalid state can never silently downgrade to the legacy
path, the envelope and the active state attach together, and the parent is untouched.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from src.application.deep_execution import DeepExecutionService, DEEP_V1_BUDGET
from src.application.deep_handoff import DeepHandoffService
from src.application.standard_continuation import StandardContinuationService
from src.web.research.deep_runtime import (
    SEED_FINAL_BACKEND,
    build_execution_envelope,
    content_available_ids,
    deep_wall_elapsed_seconds,
    effective_deep_base_elapsed,
    load_execution_envelope,
    materialization_provenance,
    materialized_content,
    seed_candidate_identity,
    seed_char_charge,
    seed_sources_by_url,
    validate_execution_envelope,
    verify_seed_sources,
)
from src.web.research.standard_plan import PLAN_SCHEMA
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent


class CountingDispatcher:
    """Stands in for the real dispatcher so a test can assert it was never called."""

    def __init__(self, outcome=None):
        self.calls = 0
        self._outcome = outcome

    def execute(self, run_id):
        self.calls += 1
        if self._outcome is not None:
            return self._outcome
        return None


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


@pytest.fixture
def ctx(saved_parent):
    """A parent with a completed Standard artifact and a prepared Deep child."""

    repository, runs, parent, created = saved_parent
    gateway = Gateway()
    clock = [created + timedelta(seconds=3)]
    continuation = StandardContinuationService(
        repository, runs, gateway, clock=lambda: clock[0], planner_factory=lambda: planner
    )
    outcome = continuation.continue_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    assert outcome.status == "completed"
    assert outcome.result["unresolved_gaps"]

    prepared = DeepHandoffService(repository, runs).prepare(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    assert prepared.status == "prepared"

    dispatcher = CountingDispatcher()
    service = DeepExecutionService(
        repository, runs, dispatcher, clock=lambda: clock[0]
    )
    return service, repository, runs, parent, clock, prepared, dispatcher


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


@pytest.mark.parametrize("policy,allowed", [
    ({"web_policy": "auto", "web_allowed": True, "reason": "allowed"}, True),
    ({"web_policy": "off", "web_allowed": False, "reason": "web_disabled_by_user"}, False),
    ({"web_policy": "ask", "web_allowed": False, "reason": "web_consent_required"}, False),
    (None, False), ("invalid", False),
])
def test_admission_transfers_owned_policy_without_defaulting_to_permission(ctx, policy, allowed):
    from src.application.active_research_runtime import _default_policy_check

    service, repository, runs, parent, _, prepared, _ = ctx
    tamper(repository, parent, lambda snap: snap.update(external_data_policy=policy))
    before = snapshot(repository, parent)
    # A stale child hint cannot grant access denied by the parent.
    child = runs.get(prepared.child_run_id)
    runs.attach_pending_context(child.id, expected_version=child.version,
                                research_context={**child.research_context,
                                                  "external_data_policy": {"web_allowed": True}})
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    context = runs.get(child.id).research_context
    assert _default_policy_check(context, "research_claim_planning") is allowed
    if isinstance(policy, dict):
        assert context["external_data_policy"] == policy
    else:
        assert "external_data_policy" not in context
    assert snapshot(repository, parent) == before
    assert context["deep"]["execution"]["publication_authority"] is False


# --- deep_runtime helpers ---------------------------------------------------------


def test_envelope_is_derived_and_validated():
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    envelope = build_execution_envelope(
        parent_turn_id="t", handoff_sha256="h", admitted_at=now
    )
    assert validate_execution_envelope(envelope) == (True, "")
    assert envelope["publication_authority"] is False
    broken = dict(envelope, deadline_at=(now + timedelta(seconds=999)).isoformat())
    assert validate_execution_envelope(broken)[0] is False


def test_envelope_rejects_authority_and_naive_timestamps():
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    envelope = build_execution_envelope(
        parent_turn_id="t", handoff_sha256="h", admitted_at=now
    )
    assert validate_execution_envelope(dict(envelope, publication_authority=True))[0] is False
    assert validate_execution_envelope(dict(envelope, admitted_at="2026-10-07T00:00:00"))[0] is False
    assert validate_execution_envelope(None)[0] is False


def test_wall_elapsed_counts_crash_downtime():
    admitted = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
    envelope = build_execution_envelope(
        parent_turn_id="t", handoff_sha256="h", admitted_at=admitted
    )
    later = admitted + timedelta(seconds=90)
    assert deep_wall_elapsed_seconds(envelope, later) == 90.0
    # A crash spends the window: the base is the larger of durable and wall time.
    assert effective_deep_base_elapsed(
        durable_elapsed_seconds=5.0, envelope=envelope, now=later
    ) == 90.0


def test_non_deep_runs_keep_their_durable_elapsed():
    assert effective_deep_base_elapsed(
        durable_elapsed_seconds=7.5, envelope=None, now=datetime.now(timezone.utc)
    ) == 7.5


def test_seed_identity_and_url_lookup_are_canonical():
    assert seed_candidate_identity("https://a/b").startswith("deep_seed_")
    seed = {
        "schema_version": "deep-seed-v1",
        "sources": [{"url": "https://a/b", "content_sha256": "x", "content": "body"}],
    }
    assert "https://a/b" in seed_sources_by_url(seed)


def test_seed_verification_fails_closed_on_a_contradiction():
    body = "durable body"
    digest = hashlib.sha256(body.encode()).hexdigest()
    good = {
        "schema_version": "deep-seed-v1",
        "sources": [{"url": "u", "content_sha256": digest, "content": body}],
    }
    assert verify_seed_sources(good)[0] is True
    tampered = {
        "schema_version": "deep-seed-v1",
        "sources": [{"url": "u", "content_sha256": digest, "content": "other"}],
    }
    assert verify_seed_sources(tampered) == (False, "seed_body_digest_mismatch")
    assert verify_seed_sources(None) == (False, "seed_absent")


def test_materialization_charges_only_the_visible_slice():
    source = {"content": "abcdefghij", "content_sha256": "d", "origin": "standard"}
    assert materialized_content(source, source_limit=4) == "abcd"
    provenance = materialization_provenance(
        seed_source=source, materialized_content="abcd", full_body_length=10
    )
    assert provenance["truncated"] is True
    assert provenance["materialized_chars"] == 4
    # The digest describes the full durable body, never the slice.
    assert provenance["source_content_sha256"] == "d"


def test_seed_char_charge_counts_each_candidate_once():
    records = [
        {
            "candidate_id": "c1",
            "final_backend": SEED_FINAL_BACKEND,
            "read_status": "read",
            "read": {"content": "12345"},
        },
        {
            "candidate_id": "c1",
            "final_backend": SEED_FINAL_BACKEND,
            "read_status": "read",
            "read": {"content": "12345"},
        },
        {"candidate_id": "c2", "read_status": "read", "read": {"content": "999"}},
    ]
    assert seed_char_charge(records) == 5


def test_content_available_unions_reads_and_seed_materializations():
    records = [
        {
            "candidate_id": "seed1",
            "final_backend": SEED_FINAL_BACKEND,
            "read_status": "read",
            "read": {"content": "x"},
        }
    ]
    assert content_available_ids(["read1"], records) == {"read1", "seed1"}


# --- E1 / E2 / E3 / E4: Deep-1 authority is re-verified ---------------------------


def test_e1_a_parent_without_a_deep_terminal_is_not_requested(ctx):
    service, repository, _runs, parent, _clock, _prepared, dispatcher = ctx
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap.pop("deep_terminal", None)
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status, rag_snapshot=snap
    )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "not_requested"
    assert dispatcher.calls == 0


def test_e2_a_malformed_deep_terminal_is_blocked(ctx):
    service, repository, _runs, parent, _clock, _prepared, dispatcher = ctx
    tamper(repository, parent, lambda snap: snap["deep_terminal"].__setitem__("state", "NOPE"))
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_e3_a_tampered_deep_handoff_is_blocked(ctx):
    service, repository, _runs, parent, _clock, _prepared, dispatcher = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"]["handoff"].__setitem__("unresolved_fields", ["x"]),
    )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_e4_a_child_lineage_mismatch_is_blocked(ctx):
    service, repository, _runs, parent, _clock, _prepared, dispatcher = ctx
    tamper(
        repository,
        parent,
        lambda snap: snap["deep_terminal"].__setitem__("child_run_id", "deep-missing"),
    )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_e5_e6_a_tampered_seed_body_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        import json

        context = json.loads(row["research_context"])
        context["deep"]["seed"]["sources"][0]["content"] = "tampered"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "seed_integrity_failure"
    assert dispatcher.calls == 0


def test_a_wrong_thread_is_blocked(ctx):
    service, _repository, _runs, parent, _clock, _prepared, dispatcher = ctx
    result = service.execute(parent_turn_id=parent.id, thread_id="other-thread")
    assert result.status == "blocked"
    assert dispatcher.calls == 0


# --- E7 / E10 / E11 / E12: atomic attach ------------------------------------------


def test_e7_first_admission_attaches_envelope_and_state_together(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status in {"deferred", "completed"}
    assert dispatcher.calls == 1
    child = runs.get(prepared.child_run_id)
    assert load_execution_envelope(child.research_context) is not None
    assert "claim_engine" in child.research_context


def test_e10_e11_an_asymmetric_attach_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    with repository.database.connect() as connection:
        import json

        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        context.pop("claim_engine", None)
        context["deep"]["execution"] = build_execution_envelope(
            parent_turn_id=parent.id,
            handoff_sha256="h",
            admitted_at=datetime.now(timezone.utc),
        )
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_e8_e9_a_non_active_claim_engine_state_is_blocked_not_legacy(ctx):
    """The dispatcher would silently run legacy here; Deep must refuse instead."""

    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    calls_after_attach = dispatcher.calls
    with repository.database.connect() as connection:
        import json

        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        # A shadow state is present and valid, but not active.
        context["claim_engine"]["mode"] = "shadow"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "claim_engine_unusable"
    assert dispatcher.calls == calls_after_attach


def test_e12_a_retry_keeps_the_same_admitted_at_and_state(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    first = load_execution_envelope(runs.get(prepared.child_run_id).research_context)
    state_before = runs.get(prepared.child_run_id).research_context["claim_engine"]
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = load_execution_envelope(runs.get(prepared.child_run_id).research_context)
    assert second["admitted_at"] == first["admitted_at"]
    assert second["deadline_at"] == first["deadline_at"]
    assert runs.get(prepared.child_run_id).research_context["claim_engine"] == state_before


# --- E42 / E44 / E45 / E47: terminal, parent untouched, no publication ------------


def test_e42_a_terminal_child_is_not_executed_again(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET status = 'completed' WHERE id = ?",
            (prepared.child_run_id,),
        )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "completed"
    assert result.reason == "child_terminal"
    assert dispatcher.calls == 0


def test_e44_e45_the_parent_is_untouched(ctx):
    service, repository, _runs, parent, _clock, _prepared, _dispatcher = ctx
    before = snapshot(repository, parent)
    message = repository.get_chat_turn(parent.id).assistant_message
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    after = snapshot(repository, parent)
    assert after["deep_terminal"] == before["deep_terminal"]
    assert after["standard_continuation"] == before["standard_continuation"]
    assert after["lookup_terminal"] == before["lookup_terminal"]
    assert repository.get_chat_turn(parent.id).assistant_message == message
    assert after["deep_terminal"]["dispatch_status"] == "pending"


def test_e47_no_path_grants_publication_authority(ctx):
    service, repository, runs, parent, _clock, prepared, _dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    envelope = load_execution_envelope(runs.get(prepared.child_run_id).research_context)
    assert envelope["publication_authority"] is False
    assert snapshot(repository, parent)["deep_terminal"]["handoff"]["publication_authority"] is False


def test_deep_budget_profile_is_the_frozen_one():
    assert DEEP_V1_BUDGET.max_candidates == 40
    assert DEEP_V1_BUDGET.max_reads == 12
    assert DEEP_V1_BUDGET.soft_timeout_seconds == 120
    assert DEEP_V1_BUDGET.hard_timeout_seconds == 180
    assert DEEP_V1_BUDGET.max_total_chars == 80_000


# --- review round 1: durable integrity, stale resume, taxonomy ----------------------


def _child_context(repository, child_run_id):
    import json

    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?", (child_run_id,)
        ).fetchone()
        return json.loads(row["research_context"])


def _write_child_context(repository, child_run_id, context):
    import json

    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), child_run_id),
        )


def test_b1_the_envelope_records_the_real_handoff_digest(ctx):
    service, repository, runs, parent, _clock, prepared, _dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    envelope = load_execution_envelope(runs.get(prepared.child_run_id).research_context)
    expected = snapshot(repository, parent)["deep_terminal"]["handoff"]["payload_sha256"]
    assert expected
    assert envelope["handoff_sha256"] == expected


def test_b2_an_envelope_bound_to_another_parent_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    calls = dispatcher.calls
    context = _child_context(repository, prepared.child_run_id)
    context["deep"]["execution"]["parent_turn_id"] = "some-other-turn"
    _write_child_context(repository, prepared.child_run_id, context)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == calls


def test_b2_an_envelope_bound_to_another_handoff_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    calls = dispatcher.calls
    context = _child_context(repository, prepared.child_run_id)
    context["deep"]["execution"]["handoff_sha256"] = "f" * 64
    _write_child_context(repository, prepared.child_run_id, context)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == calls


def test_b3_a_present_malformed_envelope_is_blocked_not_reattached(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    calls = dispatcher.calls
    context = _child_context(repository, prepared.child_run_id)
    original = context["deep"]["execution"]
    context["deep"]["execution"] = "garbage"
    _write_child_context(repository, prepared.child_run_id, context)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == calls
    # It was not overwritten with a fresh envelope.
    assert _child_context(repository, prepared.child_run_id)["deep"]["execution"] == "garbage"
    assert original


def test_b4_seed_sources_that_disagree_with_refs_are_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    context = _child_context(repository, prepared.child_run_id)
    # The refs stay trusted; only the data plane the runtime consumes is rewritten.
    context["deep"]["seed"]["sources"][0]["url"] = "https://evil.example/x"
    _write_child_context(repository, prepared.child_run_id, context)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "seed_integrity_failure"
    assert dispatcher.calls == 0


def test_b4_a_changed_field_association_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    context = _child_context(repository, prepared.child_run_id)
    context["deep"]["seed"]["sources"][0]["fields"] = ["some_other_field"]
    _write_child_context(repository, prepared.child_run_id, context)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_b4_a_changed_origin_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    context = _child_context(repository, prepared.child_run_id)
    context["deep"]["seed"]["sources"][0]["origin"] = "forged_origin"
    _write_child_context(repository, prepared.child_run_id, context)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_b6_a_stale_running_child_is_recoverable_not_deferred(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    calls = dispatcher.calls
    with repository.database.connect() as connection:
        import json

        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        # A dead owner: the operation started long ago.
        context["operation"]["active_operation_started_at"] = "2000-01-01T00:00:00+00:00"
        connection.execute(
            "UPDATE web_lookup_runs SET status = 'running', research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status != "blocked"
    assert dispatcher.calls == calls + 1


def test_b6_a_live_running_child_is_deferred(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx
    service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    calls = dispatcher.calls
    with repository.database.connect() as connection:
        import json

        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = json.loads(row["research_context"])
        context["operation"]["active_operation_started_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        connection.execute(
            "UPDATE web_lookup_runs SET status = 'running', research_context = ? WHERE id = ?",
            (json.dumps(context), prepared.child_run_id),
        )
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "deferred"
    assert result.reason == "lease_busy"
    assert dispatcher.calls == calls


def test_a_lease_race_is_deferred_not_blocked(ctx):
    """A dispatch that loses the operation race is contention, not an integrity failure.

    The racer is simulated honestly: another owner acquires the run first, so the durable child
    really is running with a live owner by the time this call loses.
    """

    service, repository, runs, parent, _clock, prepared, dispatcher = ctx

    class RacingDispatcher:
        def __init__(self):
            self.calls = 0

        def execute(self, run_id):
            self.calls += 1
            with repository.database.connect() as connection:
                import json

                row = connection.execute(
                    "SELECT research_context FROM web_lookup_runs WHERE id = ?", (run_id,)
                ).fetchone()
                context = json.loads(row["research_context"])
                context["operation"]["active_operation_started_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                connection.execute(
                    "UPDATE web_lookup_runs SET status = 'running', research_context = ? "
                    "WHERE id = ?",
                    (json.dumps(context), run_id),
                )
            raise ValueError("WebLookupRun is not resumable")

    racing = RacingDispatcher()
    service.dispatch = racing
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "deferred"
    assert result.reason == "lease_busy"
    assert racing.calls == 1


def test_an_unknown_error_is_not_converted_to_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, _dispatcher = ctx

    class Exploding:
        def execute(self, run_id):
            raise RuntimeError("provider exploded")

    service.dispatch = Exploding()
    with pytest.raises(RuntimeError):
        service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)


# --- review round 2: attach-conflict revalidation and runtime error propagation ----


def _winner_then_lose(service, repository, tamper):
    """Make the conflict path genuinely run.

    A concurrent caller wins the compare-and-swap by writing a valid pair through the real
    repository call; its durable context is then tampered; and this caller returns None so it
    becomes the loser and must reload and revalidate the winner's work.
    """

    real = service.runs.attach_pending_context
    state = {"winner_written": False, "conflict_seen": False}

    def patched(run_id, *, expected_version, research_context):
        # One call does both: the winner's valid pair lands in the database, it is then
        # tampered, and this caller is told it lost so the conflict path has to run.
        state["winner_written"] = True
        real(run_id, expected_version=expected_version, research_context=research_context)
        context = _child_context(repository, run_id)
        tamper(context)
        _write_child_context(repository, run_id, context)
        state["conflict_seen"] = True
        return None

    service.runs.attach_pending_context = patched
    return state


def test_a_attach_conflict_with_a_malformed_envelope_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx

    def tamper(context):
        context["deep"]["execution"] = "garbage"

    state = _winner_then_lose(service, repository, tamper)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)

    assert state["winner_written"] and state["conflict_seen"]
    assert result.status == "blocked"
    assert dispatcher.calls == 0
    # The malformed winner context was left exactly as written, not repaired.
    assert _child_context(repository, prepared.child_run_id)["deep"]["execution"] == "garbage"


def test_a_attach_conflict_with_a_wrong_handoff_hash_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx

    def tamper(context):
        context["deep"]["execution"]["handoff_sha256"] = "f" * 64

    state = _winner_then_lose(service, repository, tamper)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)

    assert state["winner_written"] and state["conflict_seen"]
    assert result.status == "blocked"
    assert dispatcher.calls == 0


def test_a_attach_conflict_with_a_wrong_child_owner_is_blocked(ctx):
    service, repository, runs, parent, _clock, prepared, dispatcher = ctx

    def tamper(_context):
        with repository.database.connect() as connection:
            connection.execute(
                "UPDATE web_lookup_runs SET owner_thread_id = ? WHERE id = ?",
                ("another-thread", prepared.child_run_id),
            )

    state = _winner_then_lose(service, repository, tamper)
    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)

    assert state["winner_written"] and state["conflict_seen"]
    assert result.status == "blocked"
    assert result.reason == "owner_mismatch"
    assert dispatcher.calls == 0


def test_b_a_boundary_tamper_is_blocked_and_touches_no_model_or_network(ctx):
    """The real service -> dispatcher -> runtime path must fail closed, not report lease_busy.

    The runtime marks the child running before it revalidates, so a naive handler would report
    "another worker is busy" instead of the integrity failure it actually detected.
    """

    from src.application.research_web_lookup_dispatch import (
        ClaimEngineDispatchWebLookupService,
    )

    service, repository, runs, parent, _clock, prepared, _dispatcher = ctx

    class NoNetworkGateway:
        def __init__(self):
            self.calls = 0

        def __getattr__(self, name):
            def _boom(*_args, **_kwargs):
                self.calls += 1
                raise AssertionError(f"Deep must not reach the network: {name}")

            return _boom

    gateway = NoNetworkGateway()
    real = ClaimEngineDispatchWebLookupService(
        runs, active_gateway_factory=lambda: gateway
    )

    class TamperingDispatcher:
        def __init__(self):
            self.calls = 0

        def execute(self, run_id):
            self.calls += 1
            # Tamper exactly at the dispatch boundary, after service validation passed.
            context = _child_context(repository, run_id)
            context["deep"]["seed"]["sources"][0]["content"] = "tampered at the boundary"
            _write_child_context(repository, run_id, context)
            return real.execute(run_id)

    tampering = TamperingDispatcher()
    service.dispatch = tampering

    result = service.execute(parent_turn_id=parent.id, thread_id=parent.thread_id)

    assert result.status == "blocked"
    assert result.reason == "seed_integrity_failure"
    assert tampering.calls == 1
    assert gateway.calls == 0
