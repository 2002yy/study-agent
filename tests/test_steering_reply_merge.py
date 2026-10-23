"""Concurrency contract for provisional replies.

The research executor and the API thread write the same run context.  A
supplement accepted by the API must survive an executor checkpoint that still
holds a pre-steering snapshot, and no two contents may ever share a content
version.
"""

import json

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.steering_replies import (
    LIFECYCLE_OPEN,
    find_reply,
    merge_steering_replies,
    reply_id_for_steering,
)


def _service(tmp_path):
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    return WebLookupService(repository, object()), repository


def test_acknowledgement_is_durable_in_the_same_write_as_the_supplement(tmp_path):
    service, repository = _service(tmp_path)
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread1",
        owner_turn_id="turn1",
        research_mode="deep",
    )
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")

    replies = steered.research_context["steering_replies"]
    assert len(replies) == 1
    assert replies[0]["scope"] == "steering"
    assert replies[0]["lifecycle"] == LIFECYCLE_OPEN
    assert replies[0]["turn_id"] == "turn1"
    assert "尚未生成模型分析" in replies[0]["text"]
    # The receipt and its reply share one atomic update: a successful steer is
    # already durable, never a state the caller has to guess about.
    assert len(steered.research_context["deep"]["steering"]) == 1


def test_stale_executor_checkpoint_cannot_erase_a_new_reply(tmp_path):
    service, repository = _service(tmp_path)
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread1",
        owner_turn_id="turn1",
        research_mode="deep",
    )
    stale_context = json.loads(json.dumps(run.research_context))
    operation = service.begin_tool_trace(run.id)
    steered = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    reply_id = reply_id_for_steering(run.id, steered.research_context["deep"]["steering"][0]["id"])

    # The executor checkpoints a snapshot taken before the supplement arrived.
    saved = repository.checkpoint(
        run.id,
        operation_id=operation,
        research_context=stale_context,
        query_attempts=[],
        selected_sources=[],
        rejected_sources=[],
        items=[],
        warnings=[],
    )
    replies = saved.research_context.get("steering_replies") or []
    assert find_reply(replies, reply_id) is not None
    assert len(saved.research_context["deep"]["steering"]) == 1


def test_repeated_steer_with_one_request_id_stays_idempotent(tmp_path):
    service, repository = _service(tmp_path)
    run = service.create(
        "比较 Photoshop 和开源替代品",
        owner_thread_id="thread1",
        owner_turn_id="turn1",
        research_mode="deep",
    )
    first = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    second = service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
    assert len(second.research_context["deep"]["steering"]) == 1
    assert len(second.research_context["steering_replies"]) == 1
    assert second.version == first.version  # an idempotent retry writes nothing new


def test_not_running_is_reported_as_such_not_as_a_write_conflict(tmp_path):
    service, repository = _service(tmp_path)
    run = service.create("比较 Photoshop 和开源替代品", owner_thread_id="thread1")
    repository.complete(run.id, operation_id=service.begin_tool_trace(run.id),
                        items=[], source_block="", warnings=[], research_context=run.research_context,
                        query_attempts=[], selected_sources=[], rejected_sources=[])
    try:
        service.steer(run.id, content="再考虑 Agent 自动编辑")
    except ValueError as exc:
        assert "not running" in str(exc)
        assert "conflicted" not in str(exc)
    else:
        raise AssertionError("steering a finished run must fail")


def test_conflict_keeps_authoritative_content_and_never_renumbers_stale_analysis():
    run_id = "web_lookup_run1"
    reply_id = reply_id_for_steering(run_id, "s1")
    state = {"round": 3, "notes": 4, "revision": "rev-a"}
    durable = {"reply_id": reply_id, "content_version": 7, "stage": "analysis",
               "text": "durable", "content_state": state}
    incoming = {"reply_id": reply_id, "content_version": 7, "stage": "analysis",
                "text": "incoming", "content_state": state}
    merged = merge_steering_replies(
        {"steering_replies": [incoming]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id)
    # Same state: the first successful atomic write stays authoritative.
    assert reply["text"] == "durable"
    assert reply["content_version"] == 7
    # A stale writer carrying an older research state cannot promote itself.
    stale = {"reply_id": reply_id, "content_version": 12, "stage": "analysis",
             "text": "stale", "content_state": {"round": 1, "notes": 0, "revision": "rev-0"}}
    merged = merge_steering_replies(
        {"steering_replies": [stale]}, {"steering_replies": [durable]}
    )
    assert find_reply(merged["steering_replies"], reply_id)["text"] == "durable"
