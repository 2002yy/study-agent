"""Terminal freeze: a finished run cannot be reopened by a late writer.

The three risks under review:

* ``pending`` (accepted but not started) is **not** terminal and must never be
  frozen as if the research had ended;
* ``completed`` / ``cancelled`` / ``failed`` freeze replies durably, so a late
  checkpoint or SSE event cannot reopen one or rewrite its text;
* a stale writer's snapshot never outranks the durable terminal state.
"""

import json

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.steering_replies import (
    LIFECYCLE_CLOSED,
    LIFECYCLE_OPEN,
    close_replies,
    find_reply,
    merge_steering_replies,
    reply_id_for_steering,
    reply_projection,
)


def _service(tmp_path):
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    return WebLookupService(repository, object()), repository


def _started(tmp_path):
    service, repository = _service(tmp_path)
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread1",
        owner_turn_id="turn1",
        research_mode="deep",
    )
    return service, repository, run


def _steer(service, run_id):
    steered = service.steer(run_id, content="再考虑 Agent 自动编辑", request_id="req-1")
    entry_id = steered.research_context["deep"]["steering"][0]["id"]
    return reply_id_for_steering(run_id, entry_id)


def test_pending_is_not_a_terminal_state(tmp_path):
    service, repository, run = _started(tmp_path)
    reply_id = _steer(service, run.id)
    current = repository.get(run.id)
    assert current.status == "pending"
    # Accepted but not started: the receipt stays live, never frozen.
    projected = reply_projection(
        current.research_context,
        run_id=current.id,
        turn_id="turn1",
        active=current.status in {"pending", "running"},
    )
    assert find_reply(projected, reply_id)["lifecycle"] == LIFECYCLE_OPEN


def test_cancelled_run_freezes_replies_and_refuses_late_writes(tmp_path):
    service, repository, run = _started(tmp_path)
    reply_id = _steer(service, run.id)
    operation = service.begin_tool_trace(run.id)
    cancelled = repository.finish_cancel(run.id, operation_id=operation)
    assert cancelled.status == "cancelled"
    frozen = find_reply(cancelled.research_context["steering_replies"], reply_id)
    assert frozen["lifecycle"] == LIFECYCLE_CLOSED
    # The freeze must name the authority that produced it, so a merge can tell
    # it apart from a writer merely claiming a reply is closed.
    assert frozen["lifecycle_closed_by"] == "run_terminal"
    assert frozen["closed_run_status"] == "cancelled"

    # A late executor checkpoint cannot even reach the row: cancellation is terminal.
    try:
        repository.checkpoint(
            run.id,
            operation_id=operation,
            research_context=cancelled.research_context,
            query_attempts=[],
            selected_sources=[],
            rejected_sources=[],
            items=[],
            warnings=[],
        )
    except ValueError as exc:
        assert "conflict" in str(exc) or "running" in str(exc)
    else:
        raise AssertionError("a cancelled run must not accept a checkpoint")
    assert find_reply(repository.get(run.id).research_context["steering_replies"], reply_id)[
        "lifecycle"
    ] == LIFECYCLE_CLOSED


def test_failed_run_freezes_replies(tmp_path, monkeypatch):
    from tests.test_deep_planner_production import (
        POLICY,
        ScriptedGateway,
        _production_service,
        _result,
    )

    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"photoshop": [_result("https://example.org/automation", "自动化接口")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread-1", owner_turn_id="turn-1", research_mode="deep",
    )
    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
        return original_search(query, max_items=max_items)

    gateway.search = search

    def completion(instruction, payload):
        if "sub_questions" in instruction:
            return json.dumps({"sub_questions": ["photoshop 自动化接口"]})
        # Fail after the supplement was accepted and one round really ran.
        raise RuntimeError("planner exploded")

    service.planner._completion = completion
    service.execute(run.id, raise_on_error=False)
    latest = service.repository.get(run.id)
    assert latest.status == "failed"
    replies = latest.research_context.get("steering_replies") or []
    assert replies
    assert all(reply["lifecycle"] == LIFECYCLE_CLOSED for reply in replies)
    assert all(reply["lifecycle_closed_by"] == "run_terminal" for reply in replies)
    assert all(reply["closed_run_status"] == "failed" for reply in replies)


def test_completed_run_freezes_replies(tmp_path, monkeypatch):
    from tests.test_deep_planner_production import (
        POLICY,
        ScriptedGateway,
        _production_service,
        _result,
    )

    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"photoshop": [_result("https://example.org/automation", "自动化接口")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)

    def completion(instruction, payload):
        if "sub_questions" in instruction:
            return json.dumps({"sub_questions": ["photoshop 自动化接口"]})
        return json.dumps({"done": True, "additional": [], "compute": None,
                           "steering_understandings": [], "interim_analysis": None})

    service.planner._completion = completion
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread-1", owner_turn_id="turn-1", research_mode="deep",
    )
    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
        return original_search(query, max_items=max_items)

    gateway.search = search
    completed = service.execute(run.id)
    replies = completed.research_context["steering_replies"]
    assert replies
    assert all(reply["lifecycle"] == LIFECYCLE_CLOSED for reply in replies)
    # Not "running": the provenance must name the state actually being written.
    assert all(reply["lifecycle_closed_by"] == "run_terminal" for reply in replies)
    assert all(reply["closed_run_status"] == "completed" for reply in replies)


def test_a_late_open_snapshot_never_reopens_a_closed_reply():
    reply_id = "web_lookup_run1:steer:s1"
    # A freeze is authoritative only with the run's provenance (B3): a stored
    # "closed" without it is not a state that may be kept.
    closed = {
        "reply_id": reply_id, "content_version": 3, "lifecycle": LIFECYCLE_CLOSED,
        "lifecycle_closed_by": "run_terminal", "closed_run_status": "completed",
        "stage": "analysis", "text": "frozen",
        "content_state": {"round": 2, "notes": 2, "revision": ""},
    }
    late_open = {
        "reply_id": reply_id, "content_version": 9, "lifecycle": LIFECYCLE_OPEN,
        "stage": "evidence_update", "text": "reopened",
        "content_state": {"round": 5, "notes": 9, "revision": "rev-z"},
    }
    merged = merge_steering_replies(
        {"steering_replies": [late_open]}, {"steering_replies": [closed]}
    )
    reply = find_reply(merged["steering_replies"], reply_id)
    assert reply["lifecycle"] == LIFECYCLE_CLOSED
    assert reply["text"] == "frozen"

def test_a_claimed_close_without_run_authority_never_freezes():
    """Only the run's terminal state may freeze; a bare claim is inert.

    A writer that stamps ``closed`` without ``run_terminal`` provenance must not
    take effect, however new its content claims to be - otherwise a display-only
    writer could silently end a reply the run is still updating.
    """
    reply_id = "web_lookup_run1:steer:s1"
    live = {
        "reply_id": reply_id, "content_version": 2, "lifecycle": LIFECYCLE_OPEN,
        "stage": "evidence_update", "text": "初步看可行。",
        "content_state": {"round": 1, "notes": 2, "revision": ""},
    }
    for claimed in (
        {"lifecycle": LIFECYCLE_CLOSED},
        {"lifecycle": LIFECYCLE_CLOSED, "lifecycle_closed_by": "executor"},
    ):
        incoming = {**live, "content_version": 7, "text": "claimed", **claimed}
        merged = merge_steering_replies(
            {"steering_replies": [incoming]}, {"steering_replies": [live]}
        )
        reply = find_reply(merged["steering_replies"], reply_id)
        assert reply["lifecycle"] == LIFECYCLE_OPEN, claimed
        assert reply["text"] == "初步看可行。"


def test_close_replies_stamps_authority_and_bumps_version():
    replies = [
        {
            "reply_id": "r1", "content_version": 4, "lifecycle": LIFECYCLE_OPEN,
            "stage": "analysis", "text": "x", "content_state": {},
        },
        {
            "reply_id": "r2", "content_version": 9, "lifecycle": LIFECYCLE_CLOSED,
            "lifecycle_closed_by": "run_terminal", "stage": "analysis", "text": "y",
            "content_state": {},
        },
    ]
    closed = close_replies(replies, now="2026-10-18T00:00:00+00:00", run_status="partial")
    assert closed[0]["lifecycle"] == LIFECYCLE_CLOSED
    assert closed[0]["content_version"] == 5  # the freeze is a content change
    assert closed[0]["lifecycle_closed_by"] == "run_terminal"
    assert closed[0]["closed_run_status"] == "partial"
    # An already frozen reply is not re-stamped or re-versioned.
    assert closed[1]["content_version"] == 9

def test_an_illegitimate_durable_close_is_not_kept():
    """The reverse control: a stored "closed" without run provenance is not a freeze.

    Without this, a writer that merely stamped ``closed`` could permanently hide
    a judgment the run is still updating.
    """
    reply_id = "web_lookup_run1:steer:s1"
    illegitimate = {
        "reply_id": reply_id, "content_version": 3, "lifecycle": LIFECYCLE_CLOSED,
        "lifecycle_closed_by": "executor", "based_on_version": 2,
        "stage": "analysis", "text": "claimed",
        "content_state": {"round": 2, "notes": 2, "revision": ""},
    }
    legitimate_update = {
        "reply_id": reply_id, "content_version": 4, "lifecycle": LIFECYCLE_OPEN,
        "based_on_version": 3, "stage": "evidence_update", "text": "still working",
        "content_state": {"round": 3, "notes": 4, "revision": ""},
    }
    merged = merge_steering_replies(
        {"steering_replies": [legitimate_update]}, {"steering_replies": [illegitimate]}
    )
    reply = find_reply(merged["steering_replies"], reply_id)
    assert reply["lifecycle"] == LIFECYCLE_OPEN
    assert reply["text"] == "still working"

    # ...while a freeze with the run's provenance still wins.
    authoritative = {**illegitimate, "lifecycle_closed_by": "run_terminal"}
    merged_authoritative = merge_steering_replies(
        {"steering_replies": [legitimate_update]}, {"steering_replies": [authoritative]}
    )
    assert find_reply(merged_authoritative["steering_replies"], reply_id)[
        "lifecycle"
    ] == LIFECYCLE_CLOSED
