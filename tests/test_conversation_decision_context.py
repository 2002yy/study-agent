"""Server snapshot ownership and durable-history projection regression tests."""

from dataclasses import replace

import pytest

from src.application.conversation_decision import ActiveResearch
from src.application.conversation_decision_context import (
    OwnedDecisionResearch,
    context_from_chat_snapshots,
)
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository


def snapshots():
    thread = ChatThread(id="chat-1", active_operation_id="operation-1")
    current = ChatTurn(
        id="turn-2",
        thread_id=thread.id,
        operation_id="operation-1",
        user_message="再考虑 Agent 自动编辑",
        created_at="2026-10-19T00:02:00+00:00",
    )
    prior = ChatTurn(
        id="turn-1",
        thread_id=thread.id,
        status="completed",
        user_message="比较 Photoshop 和开源替代品",
        assistant_message="先比较自动化接口",
        created_at="2026-10-19T00:01:00+00:00",
    )
    return thread, current, [prior, current]


def project(thread, turn, turns, **changes):
    return context_from_chat_snapshots(
        thread, turn, turns, operation_id="operation-1", **changes
    )


def test_real_persisted_chat_inputs_are_projected_without_writes(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.sqlite"))
    thread, turn, turns = snapshots()
    repository.create_chat_thread(thread)
    for item in turns:
        repository.add_chat_turn(item)
    stored_thread = repository.get_chat_thread(thread.id)
    stored_turn = repository.get_chat_turn(turn.id)
    stored_history = repository.list_chat_turns(thread.id)
    context = project(stored_thread, stored_turn, stored_history)
    assert context.user_message == turn.user_message
    assert context.history == (
        ("user", turns[0].user_message),
        ("assistant", turns[0].assistant_message),
    )
    assert context.request_id.startswith("decision_") and len(context.request_id) <= 160
    assert repository.get_chat_thread(thread.id) == stored_thread
    assert repository.list_chat_turns(thread.id) == stored_history
    assert project(stored_thread, stored_turn, stored_history) == context


@pytest.mark.parametrize(
    "change",
    [
        {"status": "archived"},
        {"active_operation_id": "other-operation"},
        {"archive_after_cancel_operation_id": "operation-1"},
    ],
)
def test_inactive_or_reassigned_threads_cannot_produce_a_decision(change):
    thread, turn, turns = snapshots()
    with pytest.raises(ValueError, match="not active or owned"):
        project(replace(thread, **change), turn, turns)


@pytest.mark.parametrize(
    "change",
    [
        {"status": "completed"},
        {"status": "failed"},
        {"status": "cancelled"},
        {"cancel_requested_at": "2026-10-19T00:03:00+00:00"},
        {"operation_id": "old-operation"},
        {"thread_id": "other-thread"},
    ],
)
def test_stopped_or_foreign_turns_cannot_produce_a_decision(change):
    thread, turn, turns = snapshots()
    with pytest.raises(ValueError, match="not active or owned"):
        project(thread, replace(turn, **change), turns)


@pytest.mark.parametrize("status", ["pending", "streaming"])
def test_current_partial_reply_is_rejected_until_context_can_preserve_it(status):
    thread, turn, turns = snapshots()
    continued = replace(turn, status=status, assistant_message="已经给出的部分回答")
    with pytest.raises(ValueError, match="current partial reply"):
        project(thread, continued, [turns[0], continued])


def test_cross_thread_history_rejected_instead_of_leaking_into_prompt():
    thread, turn, turns = snapshots()
    with pytest.raises(ValueError, match="another thread"):
        project(thread, turn, [replace(turns[0], thread_id="other-thread"), turn])


def test_current_turn_must_exist_exactly_once_and_match_persisted_snapshot():
    thread, turn, turns = snapshots()
    for history in (
        [],
        [turns[0]],
        [turns[0], replace(turn, user_message="unpersisted edit")],
    ):
        with pytest.raises(ValueError, match="missing or inconsistent"):
            project(thread, turn, history)
    with pytest.raises(ValueError, match="duplicate"):
        project(thread, turn, turns + [turn])


def test_future_failed_and_partial_replies_do_not_become_completed_history():
    thread, turn, turns = snapshots()
    failed = replace(
        turns[0], id="failed", status="failed", assistant_message="partial"
    )
    future = replace(turns[0], id="future", created_at="2026-10-19T00:04:00+00:00")
    assert (
        project(thread, turn, turns + [failed, future]).history
        == project(thread, turn, turns).history
    )


def test_operation_and_session_identity_are_isolated_and_retry_stable():
    thread, turn, turns = snapshots()
    original = project(thread, turn, turns).request_id
    newer_turn = replace(turn, operation_id="operation-2")
    newer_thread = replace(thread, active_operation_id="operation-2")
    retried = context_from_chat_snapshots(
        newer_thread, newer_turn, [turns[0], newer_turn], operation_id="operation-2"
    )
    assert retried.request_id != original
    foreign_thread = replace(thread, id="chat-2")
    foreign_turn = replace(turn, thread_id=foreign_thread.id)
    foreign = project(
        foreign_thread,
        foreign_turn,
        [replace(turns[0], thread_id=foreign_thread.id), foreign_turn],
    )
    assert foreign.request_id != original


def test_research_owner_and_server_capabilities_are_explicit():
    thread, turn, turns = snapshots()
    active = ActiveResearch("run-1", 3, "比较自动化接口", False)
    with pytest.raises(ValueError, match="research belongs"):
        project(
            thread,
            turn,
            turns,
            active_research=OwnedDecisionResearch("other-thread", active),
        )
    context = project(
        thread,
        turn,
        turns,
        active_research=OwnedDecisionResearch(thread.id, active),
        available_tools=("search",),
        remaining_tool_calls=1,
    )
    assert context.active_research == active
    assert not context.active_research.supports_steering
    assert context.available_tools == ("search",) and context.remaining_tool_calls == 1


def test_history_is_bounded_but_current_user_message_is_not_silently_cut():
    thread, turn, turns = snapshots()
    older = [
        replace(turns[0], id=f"old-{index:02d}", user_message="x" * 9000)
        for index in range(20)
    ]
    context = project(thread, turn, older + [turn])
    assert len(context.history) == 12
    assert all(len(content) <= 8000 for _, content in context.history)
    with pytest.raises(ValueError, match="user_message"):
        long_turn = replace(turn, user_message="x" * 8001)
        project(thread, long_turn, [long_turn])
