from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.domain.runtime_entities import ChatThread, ChatTurn, NewsRun
from src.infrastructure.sqlite.database import (
    MIGRATIONS,
    RuntimeDatabase,
    apply_migrations,
)
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
    assert "runtime_migrations" in tables


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


def test_migration_failure_rolls_back_and_restart_recovers(tmp_path):
    db_path = tmp_path / "runtime.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(MIGRATIONS[0][1])
        connection.execute(
            "INSERT INTO runtime_meta(key, value) VALUES('schema_version', '1')"
        )

    def fail_after_second_statement(version: int, index: int) -> None:
        if version == 2 and index == 1:
            raise RuntimeError("injected migration failure")

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(RuntimeError, match="injected"):
            apply_migrations(connection, after_statement=fail_after_second_statement)
        thread_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_threads)")
        }
        ledger = connection.execute(
            "SELECT status, error FROM runtime_migrations WHERE version = 2"
        ).fetchone()

    assert "archived_at" not in thread_columns
    assert ledger is not None
    assert ledger[0] == "failed"
    assert "injected migration failure" in ledger[1]

    RuntimeDatabase(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        thread_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(chat_threads)")
        }
        ledger_status = connection.execute(
            "SELECT status FROM runtime_migrations WHERE version = 2"
        ).fetchone()[0]

    assert version == "2"
    assert {"archived_at", "export_path"} <= thread_columns
    assert ledger_status == "completed"


def test_concurrent_database_initialization_applies_each_migration_once(tmp_path):
    db_path = tmp_path / "runtime.db"

    def initialize() -> None:
        RuntimeDatabase(db_path).initialize()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(initialize) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        ledger = connection.execute(
            "SELECT version, status FROM runtime_migrations ORDER BY version"
        ).fetchall()
        thread_columns = [
            row[1] for row in connection.execute("PRAGMA table_info(chat_threads)")
        ]

    assert version == "2"
    assert ledger == [(1, "completed"), (2, "completed")]
    assert thread_columns.count("archived_at") == 1


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
    assert archived.version == 3


def test_archiving_chat_thread_rejects_turn_updates(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread())
    turn = repository.add_chat_turn(
        ChatTurn(thread_id=thread.id, user_message="question", status="streaming")
    )

    locked = repository.begin_archive_chat_thread(thread.id)

    assert locked.status == "archiving"
    with pytest.raises(ValueError, match="not writable"):
        repository.update_chat_turn(
            turn.id,
            assistant_message="late answer",
            status="completed",
        )


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
