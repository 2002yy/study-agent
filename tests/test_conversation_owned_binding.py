"""Real read-only SQLite snapshots and owned DeepSeek calls over fake HTTP."""

import asyncio
from contextlib import aclosing
from dataclasses import replace
import hashlib
import json
import sqlite3

import httpx
import pytest

from src.application.conversation_action_dispatch import ActionBudget
from src.application.conversation_decision_runner import DecisionBudget
from src.application.conversation_deepseek_service import DeepSeekConversationService
from src.application.conversation_owned_binding import (
    OwnedChatSnapshot,
    OwnedConversationBinding,
    OwnedConversationUnavailable,
    OwnedRunResources,
    SQLiteChatSnapshotReader,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from tests.test_conversation_decision_context import snapshots
from tests.test_conversation_deepseek_session import factory, response, settings


def setup(tmp_path):
    path = tmp_path / "owned chat.sqlite"
    repository = RuntimeRepository(RuntimeDatabase(path))
    thread, turn, turns = snapshots()
    repository.create_chat_thread(thread)
    for item in turns:
        repository.add_chat_turn(item)
    clients, requests, arguments, admitted = [], [], [], []

    def http(req):
        wire = json.loads(req.content)
        requests.append(wire)
        if "response_format" in wire:
            data = json.loads(wire["messages"][1]["content"])
            text = json.dumps(
                {
                    "schema": "conversation-decision-v1",
                    "request_id": data["request_id"],
                    "action": "answer",
                    "relation": "continuation",
                    "reason": "已有上下文",
                    "focus": "考虑Agent编辑",
                    "tool": None,
                    "target_run_id": None,
                    "target_revision": None,
                    "active_run_disposition": "none",
                }
            )
        else:
            text = "来自服务端上下文的回答"
        return httpx.Response(200, json=response(text))

    ledger = DecisionBudget(8, 1000000, 20000)

    def resources(snapshot):
        admitted.append(snapshot.turn.id)
        return OwnedRunResources(ledger, ActionBudget(4, 0), {})

    service = DeepSeekConversationService(settings(), factory(http, clients, arguments))
    binding = OwnedConversationBinding(
        service, SQLiteChatSnapshotReader(path), resources
    )
    return binding, repository, path, clients, requests, admitted, thread, turn


def test_owned_binding_uses_durable_history_without_db_writes(tmp_path):
    async def run():
        binding, repo, path, clients, requests, admitted, thread, turn = setup(tmp_path)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        session = binding.start(thread.id, turn.id, "operation-1")
        assert not clients and not requests and admitted == [turn.id]
        async with aclosing(session.events()) as events:
            result = [event async for event in events]
        assert result[-1].reason == "answered" and clients[0].is_closed()
        data = json.loads(requests[0]["messages"][1]["content"])
        assert data["user_message"] == "再考虑 Agent 自动编辑"
        assert data["history"] == [
            {"role": "user", "content": "比较 Photoshop 和开源替代品"},
            {"role": "assistant", "content": "先比较自动化接口"},
        ]
        assert data["available_tools"] == [] and data["remaining_tool_calls"] == 0
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        assert repo.get_chat_turn(turn.id).assistant_message == ""
        assert repo.get_chat_thread(thread.id).active_operation_id == "operation-1"

    asyncio.run(run())


@pytest.mark.parametrize("which", ["thread", "turn", "operation"])
def test_foreign_or_stale_identity_is_rejected_before_admission_and_sdk(
    tmp_path, which
):
    binding, _, _, clients, requests, admitted, thread, turn = setup(tmp_path)
    args = [thread.id, turn.id, "operation-1"]
    args[{"thread": 0, "turn": 1, "operation": 2}[which]] = "foreign"
    with pytest.raises(OwnedConversationUnavailable):
        binding.start(*args)
    assert not clients and not requests and not admitted


@pytest.mark.parametrize(
    "field,value",
    [
        ("cancel_requested_at", "cancelled-now"),
        ("assistant_message", "已生成的部分回复"),
        ("status", "completed"),
        ("operation_id", "other-operation"),
    ],
)
def test_cancelled_partial_completed_or_reassigned_turn_cannot_start(
    tmp_path, field, value
):
    binding, repo, _, clients, _, admitted, thread, turn = setup(tmp_path)
    if field == "cancel_requested_at":
        assert (
            repo.request_turn_cancel(turn.id, expected_operation_id="operation-1")[0]
            == "accepted"
        )
    else:
        repo.upsert_chat_turn(replace(turn, **{field: value}))
    with pytest.raises(OwnedConversationUnavailable):
        binding.start(thread.id, turn.id, "operation-1")
    assert not clients and not admitted


def test_cancellation_between_start_and_first_read_sends_no_request(tmp_path):
    async def run():
        binding, repo, _, clients, requests, _, thread, turn = setup(tmp_path)
        session = binding.start(thread.id, turn.id, "operation-1")
        assert (
            repo.request_turn_cancel(turn.id, expected_operation_id="operation-1")[0]
            == "accepted"
        )
        async with aclosing(session.events()) as stream:
            events = [event async for event in stream]
        assert events[-1].reason == "decision_failed" and not requests
        assert clients[0].is_closed()

    asyncio.run(run())


def test_cancellation_after_decision_prevents_answer_call(tmp_path):
    async def run():
        binding, repo, _, clients, requests, _, thread, turn = setup(tmp_path)
        session = binding.start(thread.id, turn.id, "operation-1")
        async with aclosing(session.events()) as stream:
            await anext(stream)
            assert (
                repo.request_turn_cancel(turn.id, expected_operation_id="operation-1")[
                    0
                ]
                == "accepted"
            )
            events = [event async for event in stream]
        assert events[-1].reason == "action_failed"
        assert len(requests) == 1 and clients[0].is_closed()

    asyncio.run(run())


def test_readonly_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "missing" / "runtime.sqlite"
    with pytest.raises(OwnedConversationUnavailable):
        SQLiteChatSnapshotReader(missing)("thread", "turn")
    assert not missing.exists() and not missing.parent.exists()


def test_reader_limits_history_to_last_six_completed_prior_turns(tmp_path):
    binding, repo, _, _, _, _, thread, turn = setup(tmp_path)
    for index in range(10):
        repo.add_chat_turn(
            replace(
                turn,
                id=f"prior-{index}",
                status="completed",
                operation_id=None,
                user_message=f"prior {index}",
                assistant_message="答",
                created_at=f"2026-10-18T00:00:{index:02d}+00:00",
            )
        )
    snapshot = binding.snapshots(thread.id, turn.id)
    assert len(snapshot.turns) == 7 and snapshot.turns[-1].id == turn.id
    assert all(item.status == "completed" for item in snapshot.turns[:-1])


def test_sqlite_reader_keeps_one_snapshot_during_concurrent_cancel(
    tmp_path, monkeypatch
):
    binding, _, path, _, _, _, thread, turn = setup(tmp_path)
    original = sqlite3.connect
    with original(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
    changed = []

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        if kwargs.get("uri"):

            def trace(sql):
                if "SELECT * FROM chat_turns WHERE id" in sql and not changed:
                    changed.append(True)
                    with original(path) as writer:
                        writer.execute(
                            "UPDATE chat_turns SET cancel_requested_at = ? WHERE id = ?",
                            ("cancelled-now", turn.id),
                        )

            connection.set_trace_callback(trace)
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    first = binding.snapshots(thread.id, turn.id)
    second = binding.snapshots(thread.id, turn.id)
    assert first.turn.cancel_requested_at is None
    assert second.turn.cancel_requested_at == "cancelled-now"


def test_host_snapshot_identity_cannot_be_substituted(tmp_path):
    binding, _, _, clients, _, admitted, thread, turn = setup(tmp_path)
    snapshot = binding.snapshots(thread.id, turn.id)
    bad = replace(
        binding,
        snapshots=lambda *args: OwnedChatSnapshot(
            replace(snapshot.thread, id="foreign"), snapshot.turn, snapshot.turns
        ),
    )
    with pytest.raises(OwnedConversationUnavailable):
        bad.start(thread.id, turn.id, "operation-1")
    assert not admitted and not clients
