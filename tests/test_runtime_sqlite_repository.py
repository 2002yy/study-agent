from __future__ import annotations

import sqlite3

from src.domain.runtime_entities import ChatThread, ChatTurn, NewsRun
from src.infrastructure.sqlite.database import RuntimeDatabase
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
    assert version == "1"


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
