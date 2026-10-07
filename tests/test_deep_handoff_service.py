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


# --- review round 2: durable handoff integrity, full lineage, fail-closed seed -----


def _tamper_ledger(repository, child_run_id, mutate):
    """Rewrite the Standard child journal in place."""

    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?", (child_run_id,)
        ).fetchone()
        context = json.loads(row["research_context"])
        mutate(context["standard"])
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), child_run_id),
        )


def _tamper_source_run(repository, source_run_id, mutate):
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context, query FROM web_lookup_runs WHERE id = ?",
            (source_run_id,),
        ).fetchone()
        mutate(row, connection, source_run_id)


# D6a: the persisted Deep handoff is tampered without updating its digest.


def test_a_tampered_durable_deep_handoff_blocks_the_retry(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    first = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.status == "prepared"

    def mutate(snap):
        snap["deep_terminal"]["handoff"]["unresolved_fields"] = ["invented_field"]

    tamper(repository, parent, mutate)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "blocked"
    assert second.reason == "handoff_integrity_failure"


def test_a_tampered_seed_ref_blocks_the_retry(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)

    def mutate(snap):
        handoff = snap["deep_terminal"]["handoff"]
        handoff["seed_source_refs"] = [{"url": "https://evil", "content_sha256": "d" * 64}]
        # Keep the payload digest consistent so only the seed refs are wrong.
        from src.web.research.deep_handoff import payload_digest

        handoff["payload_sha256"] = payload_digest(handoff)

    tamper(repository, parent, mutate)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "blocked"


# D8a: the journal's own source run id disagrees with the child lineage.


def test_a_ledger_source_run_mismatch_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, outcome = ctx
    _tamper_ledger(
        repository, outcome.child_run_id, lambda ledger: ledger.__setitem__("source_run_id", "not-the-source")
    )
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


# D8b: the source run itself is re-verified.


def test_a_source_version_mismatch_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, outcome = ctx
    _tamper_ledger(
        repository, outcome.child_run_id, lambda ledger: ledger.__setitem__("source_run_version", 999)
    )
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


def test_a_source_query_mismatch_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx

    def mutate(row, connection, run_id):
        connection.execute(
            "UPDATE web_lookup_runs SET query = ? WHERE id = ?", ("a different question", run_id)
        )

    ledger_source = service.repository.get_chat_turn(parent.id).rag_snapshot["standard_continuation"]["source_run_id"]
    _tamper_source_run(repository, ledger_source, mutate)
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


def test_a_cancelled_source_run_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    source_run_id = service.repository.get_chat_turn(parent.id).rag_snapshot["standard_continuation"]["source_run_id"]

    def mutate(row, connection, run_id):
        context = json.loads(row["research_context"])
        context.setdefault("operation", {})["cancel_requested_at"] = "2026-01-01T00:00:00+00:00"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), run_id),
        )

    _tamper_source_run(repository, source_run_id, mutate)
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


# D8c: the journal must be terminal, not just the artifact that cites it.


def test_a_non_terminal_standard_journal_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, outcome = ctx

    def mutate(ledger):
        ledger["research"]["status"] = "planning"

    _tamper_ledger(repository, outcome.child_run_id, mutate)
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"


# D9: a body that contradicts its recorded digest fails closed, with no child created.


def test_a_seed_digest_mismatch_blocks_and_creates_no_child(ctx):
    service, repository, runs, parent, _gateway, _clock, outcome = ctx
    before = len(runs.list_by_owner_thread(parent.thread_id))

    def mutate(ledger):
        for entry in ledger["entries"].values():
            if isinstance(entry.get("result"), dict) and entry["result"].get("content"):
                entry["result"]["content"] = "tampered body that no longer hashes"

    _tamper_ledger(repository, outcome.child_run_id, mutate)
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "seed_integrity_failure"
    # A blocked terminal is recorded, but no child exists and no seed was written.
    terminal = snapshot(repository, parent)["deep_terminal"]
    assert terminal["dispatch_status"] == "blocked"
    assert "child_run_id" not in terminal
    assert len(runs.list_by_owner_thread(parent.thread_id)) == before


# --- review round 3: retry integrity ----------------------------------------------


def test_a_field_association_change_blocks_the_retry(ctx):
    """A ref with the right url and digest but the wrong field association is still a tamper."""

    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)

    def mutate(snap):
        from src.web.research.deep_handoff import payload_digest

        handoff = snap["deep_terminal"]["handoff"]
        for ref in handoff["seed_source_refs"]:
            ref["fields"] = ["some_other_field"]
        handoff["payload_sha256"] = payload_digest(handoff)

    tamper(repository, parent, mutate)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "blocked"


def test_an_origin_change_blocks_the_retry(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)

    def mutate(snap):
        from src.web.research.deep_handoff import payload_digest

        handoff = snap["deep_terminal"]["handoff"]
        for ref in handoff["seed_source_refs"]:
            # A value the durable journal never recorded.
            ref["origin"] = "forged_origin"
        handoff["payload_sha256"] = payload_digest(handoff)

    tamper(repository, parent, mutate)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "blocked"


def test_a_successful_retry_preserves_the_handoff_digest(ctx):
    service, _repository, _runs, parent, _gateway, _clock, _outcome = ctx
    first = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.handoff_sha256
    assert second.handoff_sha256 == first.handoff_sha256


def test_a_blocked_retry_preserves_the_first_reason(ctx):
    """First terminal wins: a blocked outcome is returned as decided, not re-derived."""

    service, repository, _runs, parent, _gateway, _clock, outcome = ctx

    def mutate(ledger):
        for entry in ledger["entries"].values():
            if isinstance(entry.get("result"), dict) and entry["result"].get("content"):
                entry["result"]["content"] = "tampered body that no longer hashes"

    _tamper_ledger(repository, outcome.child_run_id, mutate)
    first = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.status == "blocked"
    assert first.reason == "seed_integrity_failure"
    assert second.status == "blocked"
    assert second.reason == first.reason


# --- addendum K: the remaining retry controls -------------------------------------


def _rewrite_refs(repository, parent, mutate_ref):
    """Rewrite the durable Deep handoff's seed refs and keep its digest consistent."""

    def mutate(snap):
        from src.web.research.deep_handoff import payload_digest

        handoff = snap["deep_terminal"]["handoff"]
        for ref in handoff["seed_source_refs"]:
            mutate_ref(ref)
        handoff["payload_sha256"] = payload_digest(handoff)

    tamper(repository, parent, mutate)


def test_r2_a_ref_url_change_blocks_the_retry(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    _rewrite_refs(repository, parent, lambda ref: ref.__setitem__("url", "https://evil.example/x"))
    assert service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id).status == "blocked"


def test_r3_a_ref_digest_change_blocks_the_retry(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    _rewrite_refs(repository, parent, lambda ref: ref.__setitem__("content_sha256", "d" * 64))
    assert service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id).status == "blocked"


def test_r8_a_crash_after_child_creation_reuses_the_same_child(ctx, monkeypatch):
    """The window between create_child and the terminal write must not orphan a sibling."""

    service, repository, runs, parent, _gateway, _clock, _outcome = ctx
    from src.repositories.deep_handoff_repository import DeepHandoffRepository

    real_persist = DeepHandoffRepository.persist
    calls = {"n": 0}

    def flaky_persist(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # A hard crash, not a handled integrity failure: no terminal is written at all.
            raise RuntimeError("simulated crash before the terminal write")
        return real_persist(self, **kwargs)

    monkeypatch.setattr(DeepHandoffRepository, "persist", flaky_persist)
    with pytest.raises(RuntimeError):
        service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert "deep_terminal" not in snapshot(repository, parent)

    monkeypatch.setattr(DeepHandoffRepository, "persist", real_persist)
    second = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "prepared"

    descendants = [
        run for run in runs.list_by_owner_thread(parent.thread_id) if run.parent_run_id == _outcome.child_run_id
    ]
    assert len(descendants) == 1
    assert descendants[0].id == second.child_run_id


def test_r9_an_unknown_dispatch_status_is_blocked(ctx):
    service, repository, _runs, parent, _gateway, _clock, _outcome = ctx
    service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)

    def mutate(snap):
        snap["deep_terminal"]["dispatch_status"] = "running"

    tamper(repository, parent, mutate)
    result = service.prepare(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert result.status == "blocked"
    assert result.reason == "handoff_integrity_failure"
