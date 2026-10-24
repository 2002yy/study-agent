"""Cross-module consistency controls for provisional replies.

These are the controls the code review asked for: they drive the *production*
paths (repository checkpoint / terminal transitions and the service's own
update helpers) and then read the durable row back, instead of only asserting a
pure function's return value.

Each test names the defect it would have caught.
"""

import pytest

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.repositories.web_lookup_repository import UNEXECUTED_SUPPLEMENT_WARNING
from src.web.research.steering_replies import (
    LIFECYCLE_CLOSED,
    LIFECYCLE_OPEN,
    LIFECYCLE_SUPERSEDED,
    apply_analysis,
    content_state,
    find_reply,
    next_content_version,
    reply_id_for_steering,
    reply_projection,
)


def _started(tmp_path):
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(repository, object())
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread1",
        owner_turn_id="turn1",
        research_mode="deep",
    )
    return service, repository, run


def _durable_reply(repository, run_id, reply_id):
    context = repository.get(run_id).research_context
    return find_reply(context.get("steering_replies") or [], reply_id)


def _checkpoint(service, repository, run_id, context, operation_id):
    run = repository.get(run_id)
    return repository.checkpoint(
        run_id,
        operation_id=operation_id,
        research_context=context,
        query_attempts=run.query_attempts,
        selected_sources=run.selected_sources,
        rejected_sources=run.rejected_sources,
        items=run.items,
        warnings=run.warnings,
    )


def _with_analysis(service, repository, run_id, reply_id, operation_id, *, round_index=1, notes=2):
    """Persist a real model task understanding through the checkpoint merge."""
    context = dict(repository.get(run_id).research_context)
    current = find_reply(context["steering_replies"], reply_id)
    context["steering_replies"] = apply_analysis(
        context["steering_replies"],
        reply_id=reply_id,
        understanding={
            "changed_focus": "自动编辑改变了比较标准",
            "reason_to_check": "需要确认脚本接口是否支持批处理",
            "questions_to_verify": ["支持哪些脚本接口"],
        },
        now="2026-10-18T00:00:01+00:00",
        version=next_content_version(current),
        state=content_state(round_index=round_index, notes=notes),
        based_on=int(current.get("content_version") or 0),
    )
    _checkpoint(service, repository, run_id, context, operation_id)
    return context


def test_a_stale_mark_survives_the_persistence_merge(tmp_path):
    """B1: an invalidation that the merge refused would leave a stale judgment live."""
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    reply_id = reply_id_for_steering(run.id, entry_id)
    _with_analysis(service, repository, run.id, reply_id, operation)
    before = _durable_reply(repository, run.id, reply_id)
    assert before["stage"] == "analysis"
    assert before["stale"] is False

    # The service's own update path marks judgments older than the new round.
    context = dict(repository.get(run.id).research_context)
    deep = dict(context["deep"])
    service._deep_update_steering_replies(
        context,
        deep,
        run.id,
        incorporated=[{"id": "later-addition", "kind": "addition", "round": 2}],
    )
    _checkpoint(service, repository, run.id, context, operation)

    after = _durable_reply(repository, run.id, reply_id)
    assert after["stale"] is True, "the invalidation must survive the persistence merge"
    assert after["content_version"] > before["content_version"]
    assert "last_conflict" not in after
    # The reader sees the invalidation too, not just the database.
    projected = reply_projection(
        repository.get(run.id).research_context,
        run_id=run.id,
        turn_id="turn1",
        active=True,
    )
    assert find_reply(projected, reply_id)["stale"] is True


def test_a_supersede_survives_the_persistence_merge(tmp_path):
    """B1 (correction path): a replaced term must not stay live after a checkpoint."""
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    reply_id = reply_id_for_steering(run.id, entry_id)
    _with_analysis(service, repository, run.id, reply_id, operation)
    before = _durable_reply(repository, run.id, reply_id)
    assert before["lifecycle"] == LIFECYCLE_OPEN

    context = dict(repository.get(run.id).research_context)
    deep = dict(context["deep"])
    deep["corrections"] = [
        {"steering_id": entry_id, "old": "自动编辑", "new": "批量脚本"}
    ]
    service._deep_update_steering_replies(
        context,
        deep,
        run.id,
        incorporated=[{"id": entry_id, "kind": "correction", "round": 2}],
    )
    _checkpoint(service, repository, run.id, context, operation)

    after = _durable_reply(repository, run.id, reply_id)
    assert after["lifecycle"] == LIFECYCLE_SUPERSEDED
    assert after["stale"] is True


def test_a_steer_accepted_before_the_terminal_write_is_frozen_by_it(tmp_path):
    """B2: a reply must never read as closed while the run row is still running."""
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    reply_id = reply_id_for_steering(run.id, entry_id)

    context = dict(repository.get(run.id).research_context)
    _checkpoint(service, repository, run.id, context, operation)
    # The window the review identified: nothing may be frozen yet.
    during = _durable_reply(repository, run.id, reply_id)
    assert during["lifecycle"] == LIFECYCLE_OPEN
    assert not during.get("lifecycle_closed_by")

    completed = repository.complete(
        run.id,
        operation_id=operation,
        items=[],
        source_block="",
        warnings=[],
        research_context=context,
    )
    # The supplement was accepted but never executed, so the run is honestly
    # partial rather than a completed result that silently ignores it.
    assert completed.status == "partial"
    frozen = _durable_reply(repository, run.id, reply_id)
    assert frozen["lifecycle"] == LIFECYCLE_CLOSED
    assert frozen["lifecycle_closed_by"] == "run_terminal"
    # The freeze names the status actually written, not the "running" row it saw.
    assert frozen["closed_run_status"] == "partial"
    assert UNEXECUTED_SUPPLEMENT_WARNING in completed.warnings
    # A supplement the model never covered is reported instead of vanishing.
    assert frozen["analysis_state"] == "not_generated"


def test_a_terminal_write_that_conflicts_persists_no_freeze(tmp_path, monkeypatch):
    """B2: the freeze must not land if the terminal transition itself does not."""
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    reply_id = reply_id_for_steering(run.id, entry_id)
    context = dict(repository.get(run.id).research_context)

    # A concurrent writer that keeps winning: every attempt reads a version that
    # is already stale, so the CAS can never succeed.
    original_required = repository._required

    def racing(run_id):
        run_now = original_required(run_id)
        with repository.database.connect() as connection:
            connection.execute(
                "UPDATE web_lookup_runs SET version = version + 1 WHERE id = ?",
                (run_id,),
            )
        return run_now

    monkeypatch.setattr(repository, "_required", racing)

    with pytest.raises(ValueError):
        repository.complete(
            run.id,
            operation_id=operation,
            items=[],
            source_block="",
            warnings=[],
            research_context=context,
        )
    monkeypatch.undo()
    latest = repository.get(run.id)
    assert latest.status == "running"
    still_open = find_reply(latest.research_context["steering_replies"], reply_id)
    assert still_open["lifecycle"] == LIFECYCLE_OPEN
    assert not still_open.get("lifecycle_closed_by")


def test_a_failed_run_freezes_with_its_own_status(tmp_path):
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    reply_id = reply_id_for_steering(run.id, entry_id)

    failed = repository.fail(
        run.id,
        "planner exploded",
        operation_id=operation,
        research_context=dict(repository.get(run.id).research_context),
    )
    assert failed.status == "failed"
    frozen = _durable_reply(repository, run.id, reply_id)
    assert frozen["lifecycle"] == LIFECYCLE_CLOSED
    assert frozen["lifecycle_closed_by"] == "run_terminal"
    assert frozen["closed_run_status"] == "failed"


def test_the_terminal_projection_states_its_authority(tmp_path):
    """B6: the projection must not emit an anonymous close the client must guess at."""
    service, repository, run = _started(tmp_path)
    service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    context = repository.get(run.id).research_context

    live = reply_projection(context, run_id=run.id, turn_id="turn1", active=True)
    assert all(item["lifecycle"] == LIFECYCLE_OPEN for item in live)

    ended = reply_projection(context, run_id=run.id, turn_id="turn1", active=False)
    assert ended
    assert all(item["lifecycle"] == LIFECYCLE_CLOSED for item in ended)
    assert all(item["lifecycle_closed_by"] == "run_terminal" for item in ended)

def _steering_ids(repository, run_id):
    deep = repository.get(run_id).research_context.get("deep") or {}
    return [str(entry.get("id")) for entry in (deep.get("steering") or []) if isinstance(entry, dict)]


def test_a_superseded_reply_is_never_reopened_by_a_stale_executor(tmp_path):
    """P0: `open -> superseded` is one-way, including across a persistence merge.

    A stale executor still holding the pre-correction snapshot must not revive an
    invalidated judgment just because its research round is newer.
    """
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    reply_id = reply_id_for_steering(run.id, entry_id)
    before_correction = _with_analysis(service, repository, run.id, reply_id, operation)
    stale_snapshot = dict(before_correction)

    # The correction is accepted and persisted: the judgment is superseded.
    context = dict(repository.get(run.id).research_context)
    deep = dict(context["deep"])
    deep["corrections"] = [{"steering_id": entry_id, "old": "自动编辑", "new": "批量脚本"}]
    service._deep_update_steering_replies(
        context, deep, run.id, incorporated=[{"id": entry_id, "kind": "correction", "round": 2}]
    )
    _checkpoint(service, repository, run.id, context, operation)
    assert _durable_reply(repository, run.id, reply_id)["lifecycle"] == LIFECYCLE_SUPERSEDED

    # A stale executor checkpoints its pre-correction open snapshot.
    _checkpoint(service, repository, run.id, dict(stale_snapshot), operation)

    after = _durable_reply(repository, run.id, reply_id)
    assert after["lifecycle"] == LIFECYCLE_SUPERSEDED, "a superseded reply must not be reopened"
    assert (after.get("last_conflict") or {}).get("reason") == "superseded_reopen"
    projected = reply_projection(
        repository.get(run.id).research_context, run_id=run.id, turn_id="turn1", active=True
    )
    assert find_reply(projected, reply_id)["lifecycle"] == LIFECYCLE_SUPERSEDED


def test_a_supplement_accepted_before_completion_survives_it(tmp_path):
    """P1: the terminal write must keep the whole steering history, not just replies.

    A supplement accepted after the executor's last snapshot must exist in both
    `deep["steering"]` and `steering_replies`, and its reply must be frozen like
    any other.
    """
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    _checkpoint(service, repository, run.id, dict(repository.get(run.id).research_context), operation)
    # The executor's snapshot is now stale.
    stale_snapshot = dict(repository.get(run.id).research_context)
    # A second supplement is accepted while the executor finishes.
    service.steer(run.id, content="再补充一下导出格式的限制", request_id="req-2")

    completed = repository.complete(
        run.id,
        operation_id=operation,
        items=[],
        source_block="",
        warnings=[],
        research_context=stale_snapshot,
    )
    # The answer does not cover the requirement accepted a moment ago, so the run
    # must not report itself as a complete result.
    assert completed.status == "partial"
    assert UNEXECUTED_SUPPLEMENT_WARNING in completed.warnings
    ids = _steering_ids(repository, run.id)
    assert len(ids) == 2, f"the accepted supplement history must survive: {ids}"
    replies = repository.get(run.id).research_context["steering_replies"]
    assert len(replies) == 2, [item.get("reply_id") for item in replies]
    assert all(reply["lifecycle"] == LIFECYCLE_CLOSED for reply in replies)
    assert all(reply["lifecycle_closed_by"] == "run_terminal" for reply in replies)
    # The status the transition actually wrote, which is "partial" here because
    # the last supplement was accepted but never executed.
    assert all(reply["closed_run_status"] == "partial" for reply in replies)
    # The supplement the model never covered is reported, not silently dropped.
    assert all(reply["analysis_state"] == "not_generated" for reply in replies)
    # ...and the stronger fact is stated too: it is not in the result at all.
    assert all(reply.get("result_state") == "not_included" for reply in replies)
    # Database -> user interface: the projection the chat renders carries both the
    # per-reply state and the run warning, so nothing is silently ignored.
    projected = reply_projection(
        repository.get(run.id).research_context, run_id=run.id, turn_id="turn1", active=False
    )
    assert all(item.get("result_state") == "not_included" for item in projected)
    assert completed.warnings


def test_a_supplement_accepted_before_failure_survives_it(tmp_path):
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    stale_snapshot = dict(repository.get(run.id).research_context)
    service.steer(run.id, content="再补充一下导出格式的限制", request_id="req-2")

    failed = repository.fail(
        run.id, "planner exploded", operation_id=operation, research_context=stale_snapshot
    )
    assert failed.status == "failed"
    assert len(_steering_ids(repository, run.id)) == 2
    replies = repository.get(run.id).research_context["steering_replies"]
    assert len(replies) == 2
    assert all(reply["lifecycle_closed_by"] == "run_terminal" for reply in replies)
    assert all(reply["closed_run_status"] == "failed" for reply in replies)


def test_a_supplement_accepted_before_cancellation_survives_it(tmp_path):
    service, repository, run = _started(tmp_path)
    operation = service.begin_tool_trace(run.id)
    service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    service.steer(run.id, content="再补充一下导出格式的限制", request_id="req-2")

    cancelled = repository.finish_cancel(run.id, operation_id=operation)
    assert cancelled.status == "cancelled"
    assert len(_steering_ids(repository, run.id)) == 2
    replies = repository.get(run.id).research_context["steering_replies"]
    assert len(replies) == 2
    assert all(reply["lifecycle_closed_by"] == "run_terminal" for reply in replies)
    assert all(reply["closed_run_status"] == "cancelled" for reply in replies)
