"""Deep-4A repository: the durable publication terminal and its transaction invariants.

The controls that matter here are the ones the contract calls out: pending can only settle once,
a settled terminal is never rewritten, the source and terminal digests are re-checked at the
commit point, and a failure that is not deterministic integrity never writes a terminal.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.application.deep_continuation import DeepContinuationService
from src.application.deep_execution import DeepExecutionService
from src.application.deep_handoff import DeepHandoffService
from src.application.standard_continuation import StandardContinuationService
from src.repositories.deep_continuation_repository import DeepFinalizationError
from src.repositories.deep_publication_repository import (
    AUDITED,
    BLOCKED,
    PENDING,
    DeepPublicationRepository,
    source_run_digest,
    validate_recorded_publication,
)
from src.web.research.standard_plan import PLAN_SCHEMA
from tests.test_standard_handoff import Gateway, saved_parent as saved_parent


class _NeverDispatch:
    def execute(self, run_id):
        return None


class _Counting:
    def __init__(self):
        self.calls = 0

    def execute(self, **_kwargs):
        self.calls += 1
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
    """A parent whose Deep child reached a terminal and whose Deep terminal is completed."""

    repository, runs, parent, created = saved_parent
    gateway = Gateway()
    clock = [created + timedelta(seconds=3)]
    StandardContinuationService(
        repository, runs, gateway, clock=lambda: clock[0], planner_factory=lambda: planner
    ).continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)
    prepared = DeepHandoffService(repository, runs).prepare(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    DeepExecutionService(repository, runs, _NeverDispatch()).execute(
        parent_turn_id=parent.id, thread_id=parent.thread_id
    )
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET status = 'completed', provider_status = 'found', "
            "stop_reason = 'ready_for_binding' WHERE id = ?",
            (prepared.child_run_id,),
        )
    DeepContinuationService(
        repository, runs, _Counting()  # type: ignore[arg-type]
    ).continue_pending(parent_turn_id=parent.id, thread_id=parent.thread_id)

    repo = DeepPublicationRepository(repository.database)
    return repo, repository, runs, parent, prepared


def snapshot(repository, parent):
    return repository.get_chat_turn(parent.id).rag_snapshot


def _child_row(repository, child_run_id):
    with repository.database.connect() as connection:
        return connection.execute(
            "SELECT * FROM web_lookup_runs WHERE id = ?", (child_run_id,)
        ).fetchone()


def _audit_result(child_run_id, source_digest, *, candidate_status="mechanically_rejected"):
    zero = "a" * 64
    return {
        "schema_version": "deep-audit-artifact-v1",
        "child_run_id": child_run_id,
        "child_status": "completed",
        "deep_terminal_sha256": zero,
        "child_terminal_sha256": zero,
        "source_run_sha256": source_digest,
        "research_state_sha256": zero,
        "projection_sha256": zero,
        "draft_sha256": "",
        "audit_sha256": zero,
        "candidate_status": candidate_status,
        "audit_verdict": "fail",
        "approval_status": "audited-but-not-approved",
        "question_coverage": "unverified",
        "evidence_grounding": "unverified",
        "issue_codes": [],
        "judge_authority": "none",
        "publication_authority": False,
        "audited_at": "2026-10-07T00:00:00+00:00",
    }


# --- attach ----------------------------------------------------------------------


def test_attach_pending_records_a_bounded_candidate(ctx):
    repo, repository, runs, parent, prepared = ctx
    publication = repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    assert publication["dispatch_status"] == PENDING
    assert publication["publication_authority"] is False
    assert publication["owner"]["child_run_id"] == prepared.child_run_id
    assert publication["source"]["deep_terminal_sha256"]
    assert publication["source"]["source_run_sha256"]
    assert "result" not in publication


def test_attach_pending_is_idempotent(ctx):
    repo, _repository, _runs, parent, prepared = ctx
    first = repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    second = repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    assert first == second


def test_attach_pending_requires_a_completed_deep_terminal(ctx):
    repo, repository, _runs, parent, prepared = ctx
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap["deep_terminal"]["dispatch_status"] = "pending"
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status, rag_snapshot=snap
    )
    with pytest.raises(DeepFinalizationError):
        repo.attach_pending(
            parent_turn_id=parent.id,
            thread_id=parent.thread_id,
            child_run_id=prepared.child_run_id,
        )


def test_a_missing_child_cannot_attach(ctx):
    repo, _repository, _runs, parent, _prepared = ctx
    with pytest.raises(DeepFinalizationError):
        repo.attach_pending(
            parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id="deep-missing"
        )


# --- finalize --------------------------------------------------------------------


def test_finalize_audited_settles_once(ctx):
    repo, repository, runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    publication = repo.finalize_audited(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        audit_source_digest=digest,
        result=_audit_result(prepared.child_run_id, digest),
    )
    assert publication["dispatch_status"] == AUDITED
    assert publication["result"]["publication_authority"] is False
    assert publication["result"]["judge_authority"] == "none"
    assert publication["result"]["approval_status"] == "audited-but-not-approved"


def test_a_settled_publication_is_never_rewritten(ctx):
    repo, repository, runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    first = repo.finalize_audited(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        audit_source_digest=digest,
        result=_audit_result(prepared.child_run_id, digest),
    )
    # A later block must not flip it.
    second = repo.block(
        parent_turn_id=parent.id, thread_id=parent.thread_id, reason="late_failure"
    )
    assert second["dispatch_status"] == AUDITED
    assert second["result"] == first["result"]
    # And a later finalize must not rewrite it either.
    third = repo.finalize_audited(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        audit_source_digest="b" * 64,
        result=_audit_result(prepared.child_run_id, "b" * 64),
    )
    assert third["result"] == first["result"]


def test_first_terminal_wins_before_source_validation(ctx):
    repo, repository, runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    repo.finalize_audited(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        audit_source_digest=digest,
        result=_audit_result(prepared.child_run_id, digest),
    )
    # Damage the child after settling: the settled audit must still be returned.
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET stop_reason = 'damaged' WHERE id = ?",
            (prepared.child_run_id,),
        )
    settled = repo.finalize_audited(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        audit_source_digest="c" * 64,
        result=_audit_result(prepared.child_run_id, "c" * 64),
    )
    assert settled["dispatch_status"] == AUDITED


def test_a_changed_source_run_blocks_at_the_commit_point(ctx):
    repo, repository, runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    # The child changes between validation and commit.
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET answer_confidence = 'changed' WHERE id = ?",
            (prepared.child_run_id,),
        )
    with pytest.raises(DeepFinalizationError) as exc:
        repo.finalize_audited(
            parent_turn_id=parent.id,
            thread_id=parent.thread_id,
            audit_source_digest=digest,
            result=_audit_result(prepared.child_run_id, digest),
        )
    assert exc.value.reason == "source_run_changed"


def test_a_changed_deep_terminal_blocks_at_the_commit_point(ctx):
    repo, repository, _runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap["deep_terminal"]["reason"] = "tampered"
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status, rag_snapshot=snap
    )
    with pytest.raises(DeepFinalizationError) as exc:
        repo.finalize_audited(
            parent_turn_id=parent.id,
            thread_id=parent.thread_id,
            audit_source_digest=digest,
            result=_audit_result(prepared.child_run_id, digest),
        )
    assert exc.value.reason == "deep_terminal_integrity_failure"


# --- block -----------------------------------------------------------------------


def test_block_persists_even_when_the_source_is_broken(ctx):
    repo, repository, runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    # Break the child, then block: the corruption must not prevent the block.
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = '{}' WHERE id = ?",
            (prepared.child_run_id,),
        )
    publication = repo.block(
        parent_turn_id=parent.id, thread_id=parent.thread_id, reason="claim_engine_unusable"
    )
    assert publication["dispatch_status"] == BLOCKED
    assert publication["reason"] == "claim_engine_unusable"
    assert "result" not in publication


def test_block_with_a_wrong_owner_is_still_persisted(ctx):
    repo, repository, _runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap["deep_publication"]["owner"]["thread_id"] = "other"
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status, rag_snapshot=snap
    )
    publication = repo.block(
        parent_turn_id=parent.id, thread_id=parent.thread_id, reason="child_missing"
    )
    assert publication["dispatch_status"] == BLOCKED
    assert publication["reason"] == "publication_integrity_failure"


def test_a_raw_reason_is_bounded(ctx):
    repo, _repository, _runs, parent, prepared = ctx
    repo.attach_pending(
        parent_turn_id=parent.id, thread_id=parent.thread_id, child_run_id=prepared.child_run_id
    )
    publication = repo.block(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        reason="Traceback (most recent call last): secret",
    )
    assert publication["reason"] == "publication_integrity_failure"


# --- recorded terminal validation ------------------------------------------------


def test_validate_recorded_publication_pending(ctx):
    assert validate_recorded_publication(
        {"schema_version": "deep-publication-v1", "dispatch_status": PENDING,
         "publication_authority": False, "owner": {"thread_id": "t", "turn_id": "p"}},
        parent_turn_id="p",
        thread_id="t",
    ) == (True, "")


def test_validate_recorded_publication_rejects_a_bad_audit(ctx):
    zero = "a" * 64
    base = {
        "schema_version": "deep-publication-v1",
        "dispatch_status": AUDITED,
        "publication_authority": False,
        "owner": {"thread_id": "t", "turn_id": "p", "child_run_id": "c"},
        "source": {
            "deep_terminal_sha256": zero,
            "child_terminal_sha256": zero,
            "source_run_sha256": "d" * 64,
        },
    }
    kw = {"parent_turn_id": "p", "thread_id": "t"}
    assert validate_recorded_publication({**base, "result": None}, **kw)[0] is False
    result = _audit_result("c", "d" * 64)
    assert validate_recorded_publication({**base, "result": result}, **kw) == (True, "")
    assert validate_recorded_publication(
        {**base, "result": {**result, "publication_authority": True}}, **kw
    )[0] is False
    assert validate_recorded_publication(
        {**base, "result": {**result, "raw_body": "x"}}, **kw
    )[0] is False
    assert validate_recorded_publication(
        {**base, "result": {**result, "judge_authority": "gpt-5.6"}}, **kw
    )[0] is False
    assert validate_recorded_publication(
        {**base, "result": {**result, "approval_status": "approved"}}, **kw
    )[0] is False
    # Owner must name this parent on this thread.
    assert validate_recorded_publication(
        {**base, "owner": {"thread_id": "other", "turn_id": "p"}, "result": result}, **kw
    )[0] is False


def test_validate_recorded_publication_accepts_a_bounded_block(ctx):
    kw = {"parent_turn_id": "p", "thread_id": "t"}
    owner = {"thread_id": "t", "turn_id": "p"}
    assert validate_recorded_publication(
        {"schema_version": "deep-publication-v1", "dispatch_status": BLOCKED,
         "publication_authority": False, "reason": "child_missing", "owner": owner}, **kw
    ) == (True, "")
    assert validate_recorded_publication(
        {"schema_version": "deep-publication-v1", "dispatch_status": BLOCKED,
         "publication_authority": False, "reason": "raw traceback text", "owner": owner}, **kw
    )[0] is False
    assert validate_recorded_publication(
        {"schema_version": "deep-publication-v1", "dispatch_status": BLOCKED,
         "publication_authority": False, "reason": "child_missing", "result": {"x": 1},
         "owner": owner}, **kw
    )[0] is False


# --- service: audited is not approved, and nothing is published ---------------------


def _service(ctx):
    from src.application.deep_publication import DeepPublicationService

    repo, repository, runs, parent, prepared = ctx
    return DeepPublicationService(repository, runs), repository, runs, parent, prepared


def test_au1_au2_the_service_has_no_model_or_network_dependency():
    import inspect

    from src.application.deep_publication import DeepPublicationService

    params = set(inspect.signature(DeepPublicationService.__init__).parameters)
    # No gateway, model or client may be injected: Deep-4A is deterministic and offline.
    assert not (params & {"gateway", "model", "judge", "llm", "client"})


def test_au3_a_mechanically_valid_candidate_is_audited_not_approved(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "audited"
    result = outcome.result
    assert result["approval_status"] == "audited-but-not-approved"
    assert result["judge_authority"] == "none"
    assert result["publication_authority"] is False
    assert result["audit_verdict"] == "fail"
    assert result["candidate_status"] in {"assembled", "mechanically_rejected"}
    terminal = snapshot(repository, parent)["deep_publication"]
    assert terminal["dispatch_status"] == "audited"


def test_au6_the_audit_result_carries_no_raw_artifact(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    result = outcome.result
    for forbidden in (
        "raw_body", "selected_sources", "research_context", "evidence", "draft_text",
        "research_state", "brief", "payloads", "exception",
    ):
        assert forbidden not in result
    assert len(result["audit_sha256"]) == 64


def test_i1_to_i6_the_parent_keeps_everything_else(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    before = snapshot(repository, parent)
    message = repository.get_chat_turn(parent.id).assistant_message
    service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    after = snapshot(repository, parent)
    assert repository.get_chat_turn(parent.id).assistant_message == message
    for key in ("lookup_terminal", "standard_continuation", "deep_terminal"):
        assert after[key] == before[key]
    assert set(after) == set(before) | {"deep_publication"}


def test_c4_a_lost_result_returns_the_same_audit(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    first = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    second = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert first.status == second.status == "audited"
    assert first.result == second.result


def test_a_settled_audit_survives_a_damaged_child(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    first = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = '{}' WHERE id = ?",
            (prepared.child_run_id,),
        )
    second = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert second.status == "audited"
    assert second.result == first.result


def test_a7_an_unusable_claim_engine_blocks_durably(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    with repository.database.connect() as connection:
        import json as _json

        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = _json.loads(row["research_context"])
        context["claim_engine"]["mode"] = "shadow"
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (_json.dumps(context), prepared.child_run_id),
        )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "blocked"
    assert outcome.reason == "claim_engine_unusable"
    assert snapshot(repository, parent)["deep_publication"]["dispatch_status"] == "blocked"

def test_a_no_publication_work_is_not_requested(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap["deep_terminal"]["dispatch_status"] = "pending"
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status, rag_snapshot=snap
    )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "not_requested"
    assert "deep_publication" not in snapshot(repository, parent)


def test_a_mechanically_rejected_candidate_is_still_an_honest_audit(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    # Remove every link so the projection authorises no evidence at all.
    with repository.database.connect() as connection:
        import json as _json

        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (prepared.child_run_id,),
        ).fetchone()
        context = _json.loads(row["research_context"])
        engine = context["claim_engine"]
        engine["evidence_links"] = []
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (_json.dumps(context), prepared.child_run_id),
        )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status in {"audited", "blocked"}
    if outcome.status == "audited":
        assert outcome.result["publication_authority"] is False
        assert outcome.result["approval_status"] == "audited-but-not-approved"


# --- review round 2: real concurrency, binding and runtime isolation --------------


def test_a10_a_wrong_lineage_child_is_durably_blocked(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET parent_run_id = ? WHERE id = ?",
            ("not-the-standard-child", prepared.child_run_id),
        )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "blocked"
    assert outcome.reason == "lineage_mismatch"
    assert snapshot(repository, parent)["deep_publication"]["dispatch_status"] == "blocked"


def test_a11_a_child_changed_after_attach_blocks_at_the_commit_point(ctx):
    service, repository, runs, parent, prepared = _service(ctx)
    service.publication.attach_pending(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        child_run_id=prepared.child_run_id,
    )
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET answer_confidence = ? WHERE id = ?",
            ("changed", prepared.child_run_id),
        )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "blocked"
    assert outcome.reason == "source_run_changed"


def test_a_child_terminal_projection_changed_after_deep3_blocks(ctx):
    """The child terminal must still project the digest Deep-3 recorded."""

    service, repository, runs, parent, prepared = _service(ctx)
    # Change only the terminal projection fields, before any attach.
    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET stop_reason = ? WHERE id = ?",
            ("a_different_stop_reason", prepared.child_run_id),
        )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "blocked"
    assert outcome.reason == "deep_terminal_integrity_failure"
    assert snapshot(repository, parent)["deep_publication"]["dispatch_status"] == "blocked"


def test_c5_two_threads_attach_concurrently(ctx):
    import threading

    service, repository, runs, parent, prepared = _service(ctx)
    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    def attach():
        try:
            barrier.wait(timeout=5.0)
            results.append(
                service.publication.attach_pending(
                    parent_turn_id=parent.id,
                    thread_id=parent.thread_id,
                    child_run_id=prepared.child_run_id,
                )
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=attach) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert errors == []
    assert len(results) == 2
    assert results[0] == results[1]
    assert snapshot(repository, parent)["deep_publication"]["dispatch_status"] == "pending"


def test_c6_two_threads_finalize_concurrently(ctx):
    import threading

    service, repository, runs, parent, prepared = _service(ctx)
    service.publication.attach_pending(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        child_run_id=prepared.child_run_id,
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    barrier = threading.Barrier(2)
    outcomes: list = []
    errors: list = []

    def settle(marker: str):
        try:
            barrier.wait(timeout=5.0)
            outcomes.append(
                service.publication.finalize_audited(
                    parent_turn_id=parent.id,
                    thread_id=parent.thread_id,
                    audit_source_digest=digest,
                    result=_audit_result(
                        prepared.child_run_id,
                        digest,
                        candidate_status=(
                            "assembled" if marker == "a" else "mechanically_rejected"
                        ),
                    ),
                )
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=settle, args=(m,)) for m in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert errors == []
    assert len(outcomes) == 2
    assert outcomes[0] == outcomes[1]
    durable = snapshot(repository, parent)["deep_publication"]
    assert durable["dispatch_status"] == "audited"
    assert durable["result"] == outcomes[0]["result"]


def test_c7_audited_and_block_race_resolves_to_one_terminal(ctx):
    import threading

    service, repository, runs, parent, prepared = _service(ctx)
    service.publication.attach_pending(
        parent_turn_id=parent.id,
        thread_id=parent.thread_id,
        child_run_id=prepared.child_run_id,
    )
    digest = source_run_digest(_child_row(repository, prepared.child_run_id))
    barrier = threading.Barrier(2)
    seen: list = []
    errors: list = []

    def audit():
        try:
            barrier.wait(timeout=5.0)
            seen.append(
                service.publication.finalize_audited(
                    parent_turn_id=parent.id,
                    thread_id=parent.thread_id,
                    audit_source_digest=digest,
                    result=_audit_result(prepared.child_run_id, digest),
                )["dispatch_status"]
            )
        except Exception as exc:
            errors.append(exc)

    def block():
        try:
            barrier.wait(timeout=5.0)
            seen.append(
                service.publication.block(
                    parent_turn_id=parent.id,
                    thread_id=parent.thread_id,
                    reason="child_missing",
                )["dispatch_status"]
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=audit), threading.Thread(target=block)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)

    assert errors == []
    durable = snapshot(repository, parent)["deep_publication"]
    assert durable["dispatch_status"] in {"audited", "blocked"}
    # Both workers must observe the terminal that actually committed.
    assert seen == [durable["dispatch_status"], durable["dispatch_status"]]


def test_i7_nothing_outside_the_parent_snapshot_is_written(ctx):
    service, repository, runs, parent, prepared = _service(ctx)

    def counts():
        with repository.database.connect() as connection:
            names = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            ]
            return {
                name: connection.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                for name in names
            }

    before = counts()
    service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    after = counts()
    assert set(after) == set(before)
    for name, value in before.items():
        assert after[name] == value, name


def test_au1_au2_the_production_path_makes_no_model_or_network_call(ctx, monkeypatch):
    service, repository, runs, parent, prepared = _service(ctx)
    calls: list = []

    def _boom(*args, **kwargs):
        calls.append("called")
        raise AssertionError("Deep-4A must not reach a model or the network")

    import src.llm_client as llm

    monkeypatch.setattr(llm, "chat", _boom, raising=False)

    # AU2: no outbound socket either. Patching connect is what makes this a runtime gate rather
    # than an inference from the dependency structure.
    import socket

    def _no_connect(*_args, **_kwargs):
        calls.append("socket")
        raise AssertionError("Deep-4A must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", _no_connect, raising=False)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_connect, raising=False)

    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "audited"
    assert outcome.result["publication_authority"] is False
    assert calls == []


def test_validate_recorded_audited_binds_the_owner_child_id():
    zero = "a" * 64
    publication = {
        "schema_version": "deep-publication-v1",
        "dispatch_status": AUDITED,
        "publication_authority": False,
        "owner": {"thread_id": "t", "turn_id": "p", "child_run_id": "the-child"},
        "source": {"deep_terminal_sha256": zero, "child_terminal_sha256": zero,
                   "source_run_sha256": zero},
    }
    result = _audit_result("the-child", zero)
    kw = {"parent_turn_id": "p", "thread_id": "t"}
    assert validate_recorded_publication(
        {**publication, "result": result}, **kw
    ) == (True, "")
    # A different child id in the result must be rejected.
    assert validate_recorded_publication(
        {**publication, "result": {**result, "child_run_id": "other"}}, **kw
    )[0] is False


def test_an_explicit_null_publication_is_not_overwritten_by_block(ctx):
    service, repository, _runs, parent, _prepared = _service(ctx)
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap["deep_publication"] = None
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status,
        rag_snapshot=snap,
    )
    outcome = service.process(parent_turn_id=parent.id, thread_id=parent.thread_id)
    assert outcome.status == "blocked"
    assert outcome.reason == "publication_integrity_failure"
    # The recorded value is left exactly as it was: never recreated, never repaired.
    assert snapshot(repository, parent)["deep_publication"] is None


def test_block_declines_an_explicit_null_publication(ctx):
    """The repository itself must not treat a recorded null as absent."""

    repo, repository, _runs, parent, _prepared = ctx
    turn = repository.get_chat_turn(parent.id)
    snap = turn.rag_snapshot
    snap["deep_publication"] = None
    repository.update_chat_turn(
        turn.id, assistant_message=turn.assistant_message, status=turn.status,
        rag_snapshot=snap,
    )
    with pytest.raises(DeepFinalizationError):
        repo.block(
            parent_turn_id=parent.id,
            thread_id=parent.thread_id,
            reason="child_missing",
        )
    # The recorded null is left exactly as it was.
    assert snapshot(repository, parent)["deep_publication"] is None
