from __future__ import annotations

import sqlite3

import pytest

from src.domain.runtime_entities import ChatThread, ChatTurn, NewsRun
from src.infrastructure.sqlite.database import MIGRATIONS, RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository


def test_runtime_database_initializes_core_tables(tmp_path):
    db_path = tmp_path / "runtime.db"
    database = RuntimeDatabase(db_path)

    database.initialize()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert {
        "chat_threads",
        "chat_turns",
        "group_threads",
        "group_messages",
        "news_runs",
        "tool_runs",
        "operations",
    } <= tables
    assert version == "2"


def test_runtime_database_migrates_existing_v1_database(tmp_path):
    db_path = tmp_path / "runtime.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(MIGRATIONS[0][1])
        connection.execute(
            "INSERT INTO runtime_meta(key, value) VALUES('schema_version', '1')"
        )

    RuntimeDatabase(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        thread_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_threads)")
        }
        turn_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_turns)")
        }
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert version == "2"
    assert {"archived_at", "export_path"} <= thread_columns
    assert {"operation_id", "conversation_instruction"} <= turn_columns


def test_chat_turn_lifecycle_updates_the_same_turn(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread(settings_snapshot={"role": "nahida"}))
    turn = repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="Explain RAG",
            status="streaming",
            role="nahida",
            mode="普通",
            model="flash",
            route_snapshot={"role": "nahida"},
            rag_snapshot={"result_count": 2},
            operation_id="op_chat_1",
            conversation_instruction="be concise",
        )
    )

    updated = repository.update_chat_turn(
        turn.id,
        assistant_message="RAG means retrieval augmented generation.",
        status="completed",
    )
    turns = repository.list_chat_turns(thread.id)

    assert updated is not None
    assert updated.id == turn.id
    assert updated.status == "completed"
    assert updated.assistant_message.startswith("RAG means")
    assert [item.id for item in turns] == [turn.id]
    assert turns[0].route_snapshot == {"role": "nahida"}
    assert turns[0].operation_id == "op_chat_1"
    assert turns[0].conversation_instruction == "be concise"


def test_archived_chat_thread_rejects_new_turns(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread())
    archived = repository.archive_chat_thread(thread.id, export_path="archive.md")

    with pytest.raises(ValueError, match="not writable"):
        repository.add_chat_turn(
            ChatTurn(thread_id=thread.id, user_message="must fail")
        )

    assert archived.status == "archived"
    assert archived.export_path == "archive.md"
    assert archived.version == 2


def test_news_run_stage_transitions_are_persisted(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    run = repository.create_news_run(NewsRun(query="AI news", stage="searched", status="completed"))

    enriched = repository.update_news_run(
        run.id,
        stage="enriched",
        status="completed",
        items=[{"title": "A", "article_text": "body"}],
    )
    digested = repository.update_news_run(
        run.id,
        stage="digested",
        status="completed",
        digest="summary",
        warnings=["limited-source"],
    )
    loaded = repository.get_news_run(run.id)

    assert enriched is not None
    assert digested is not None
    assert loaded is not None
    assert loaded.id == run.id
    assert loaded.stage == "digested"
    assert loaded.items == [{"title": "A", "article_text": "body"}]
    assert loaded.digest == "summary"
    assert loaded.warnings == ["limited-source"]
