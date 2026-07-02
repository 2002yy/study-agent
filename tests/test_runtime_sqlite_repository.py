from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import (
    MIGRATIONS,
    RuntimeDatabase,
    SCHEMA_VERSION,
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
    assert version == str(SCHEMA_VERSION)
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
        tool_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tool_runs)")
        }
        version = connection.execute(
            "SELECT value FROM runtime_meta WHERE key = 'schema_version'"
        ).fetchone()[0]

    assert version == str(SCHEMA_VERSION)
    assert {
        "archived_at",
        "export_path",
        "active_operation_id",
        "active_operation_started_at",
        "archive_operation_id",
        "archive_started_at",
    } <= thread_columns
    assert {"operation_id", "conversation_instruction"} <= turn_columns
    assert {
        "reason",
        "elapsed_ms",
        "version",
        "active_operation_id",
        "active_operation_started_at",
        "previewed_at",
        "completed_at",
    } <= tool_columns


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

    assert version == str(SCHEMA_VERSION)
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

    assert version == str(SCHEMA_VERSION)
    assert ledger == [
        (version, "completed") for version in range(1, SCHEMA_VERSION + 1)
    ]
    assert thread_columns.count("archived_at") == 1


def test_v3_migration_recovers_unowned_legacy_intermediate_states(tmp_path):
    db_path = tmp_path / "runtime.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(MIGRATIONS[0][1])
        connection.executescript(MIGRATIONS[1][1])
        connection.execute(
            "INSERT INTO runtime_meta(key, value) VALUES('schema_version', '2')"
        )
        connection.execute(
            """
            INSERT INTO chat_threads(
                id, status, settings_snapshot, created_at, updated_at,
                archived_at, export_path, version
            ) VALUES ('legacy-thread', 'archiving', '{}', 'now', 'now', NULL, '', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO chat_turns(
                id, thread_id, user_message, assistant_message, status,
                role, mode, model, route_snapshot, rag_snapshot,
                parent_turn_id, operation_id, conversation_instruction,
                created_at, updated_at
            ) VALUES (
                'legacy-turn', 'legacy-thread', 'question', 'partial', 'streaming',
                '', '', '', '{}', '{}', NULL, 'old-op', '', 'now', 'now'
            )
            """
        )

    RuntimeDatabase(db_path).initialize()

    with sqlite3.connect(db_path) as connection:
        thread_status = connection.execute(
            "SELECT status FROM chat_threads WHERE id = 'legacy-thread'"
        ).fetchone()[0]
        turn_status = connection.execute(
            "SELECT status FROM chat_turns WHERE id = 'legacy-turn'"
        ).fetchone()[0]

    assert thread_status == "active"
    assert turn_status == "interrupted"


def test_chat_turn_lifecycle_updates_the_same_turn(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread(settings_snapshot={"role": "nahida"}))
    repository.acquire_chat_operation(thread.id, "op_chat_1")
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
        expected_operation_id="op_chat_1",
        enforce_operation_owner=True,
        expected_status="streaming",
        release_operation=True,
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
        ChatTurn(thread_id=thread.id, user_message="question", status="completed")
    )

    locked = repository.begin_archive_chat_thread(thread.id, operation_id="archive-op")

    assert locked.status == "archiving"
    with pytest.raises(ValueError, match="ownership lost"):
        repository.update_chat_turn(
            turn.id,
            assistant_message="late answer",
            status="completed",
        )


def test_archive_owner_rejects_concurrent_archive_and_recovers_stale_lock(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = RuntimeRepository(database)
    thread = repository.create_chat_thread(ChatThread())

    locked = repository.begin_archive_chat_thread(thread.id, operation_id="archive-a")
    assert locked.archive_operation_id == "archive-a"

    with pytest.raises(ValueError, match="already being archived"):
        repository.begin_archive_chat_thread(thread.id, operation_id="archive-b")

    with database.connect() as connection:
        connection.execute(
            "UPDATE chat_threads SET archive_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", thread.id),
        )

    recovered_repository = RuntimeRepository(database)
    recovered = recovered_repository.get_chat_thread(thread.id)
    assert recovered is not None
    assert recovered.status == "active"
    assert recovered.archive_operation_id is None

    committed_path = tmp_path / "committed-archive.md"
    committed_path.write_text("# complete archive", encoding="utf-8")
    recovered_repository.begin_archive_chat_thread(
        thread.id,
        operation_id="archive-c",
    )
    recovered_repository.reserve_archive_path(
        thread.id,
        operation_id="archive-c",
        export_path=str(committed_path),
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE chat_threads SET archive_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", thread.id),
        )

    completed_repository = RuntimeRepository(database)
    completed = completed_repository.get_chat_thread(thread.id)
    assert completed is not None
    assert completed.status == "archived"
    assert completed.export_path == str(committed_path)


def test_archive_rejects_thread_with_active_chat_operation(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread())
    repository.acquire_chat_operation(thread.id, "chat-op")

    with pytest.raises(ValueError, match="active operation"):
        repository.begin_archive_chat_thread(thread.id, operation_id="archive-op")


def test_stale_chat_operation_is_interrupted_and_lease_is_released(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = RuntimeRepository(database)
    thread = repository.create_chat_thread(ChatThread())
    repository.acquire_chat_operation(thread.id, "chat-op")
    turn = repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            status="streaming",
            operation_id="chat-op",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE chat_threads SET active_operation_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", thread.id),
        )

    recovered_repository = RuntimeRepository(database)
    recovered_thread = recovered_repository.get_chat_thread(thread.id)
    recovered_turn = recovered_repository.get_chat_turn(turn.id)

    assert recovered_thread is not None
    assert recovered_thread.active_operation_id is None
    assert recovered_turn is not None
    assert recovered_turn.status == "interrupted"


def test_concurrent_chat_operation_acquire_has_single_winner(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread())
    barrier = Barrier(2)

    def acquire(operation_id: str) -> str:
        barrier.wait(timeout=5)
        try:
            repository.acquire_chat_operation(thread.id, operation_id)
            return operation_id
        except ValueError:
            return ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = list(executor.map(acquire, ["op-a", "op-b"]))

    assert len([winner for winner in winners if winner]) == 1
    stored = repository.get_chat_thread(thread.id)
    assert stored is not None
    assert stored.active_operation_id in {"op-a", "op-b"}


def test_concurrent_operation_settings_belong_to_lease_winner(tmp_path):
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    thread = repository.create_chat_thread(ChatThread())
    barrier = Barrier(2)

    def acquire(operation_id: str) -> str:
        barrier.wait(timeout=5)
        try:
            repository.acquire_chat_operation(
                thread.id,
                operation_id,
                settings_snapshot={"owner": operation_id},
            )
            return operation_id
        except ValueError:
            return ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = list(executor.map(acquire, ["op-a", "op-b"]))

    winner = next(item for item in winners if item)
    stored = repository.get_chat_thread(thread.id)
    assert stored is not None
    assert stored.active_operation_id == winner
    assert stored.settings_snapshot == {"owner": winner}


def test_turn_completion_and_pedagogy_state_commit_atomically(tmp_path):
    db_path = tmp_path / "runtime.db"
    repository = RuntimeRepository(RuntimeDatabase(db_path))
    thread = repository.create_chat_thread(
        ChatThread(learning_state={"phase": "orientation"})
    )
    repository.acquire_chat_operation(thread.id, "operation-1")
    turn = repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            status="streaming",
            operation_id="operation-1",
        )
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_completed_turn
            BEFORE UPDATE OF status ON chat_turns
            WHEN NEW.status = 'completed'
            BEGIN
                SELECT RAISE(ABORT, 'simulated completion failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="simulated completion failure"):
        repository.complete_chat_turn_with_pedagogy(
            turn.id,
            assistant_message="answer",
            learning_state={"phase": "transfer"},
            pedagogy_snapshot={"after": {"phase": "transfer"}},
            route_snapshot={},
            rag_snapshot={},
            operation_id="operation-1",
        )

    stored_thread = repository.get_chat_thread(thread.id)
    stored_turn = repository.get_chat_turn(turn.id)
    assert stored_thread is not None
    assert stored_thread.learning_state == {"phase": "orientation"}
    assert stored_thread.active_operation_id == "operation-1"
    assert stored_turn is not None
    assert stored_turn.status == "streaming"


def test_eval_insert_failure_rolls_back_turn_and_pedagogy_state(tmp_path, monkeypatch):
    from src.pedagogy.evaluation import PedagogyEvaluationService
    from src.pedagogy.types import LearningState
    from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository

    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = RuntimeRepository(database)
    thread = repository.create_chat_thread(
        ChatThread(learning_state={"phase": "orientation"})
    )
    repository.acquire_chat_operation(thread.id, "operation-eval")
    turn = repository.add_chat_turn(
        ChatTurn(
            thread_id=thread.id,
            user_message="question",
            status="streaming",
            operation_id="operation-eval",
        )
    )
    run = PedagogyEvaluationService().evaluate_learner(
        learner_input="question",
        state=LearningState(protocol="direct_answer", objective="question"),
    )

    def fail_insert(*_args, **_kwargs):
        raise sqlite3.IntegrityError("simulated eval failure")

    monkeypatch.setattr(PedagogyEvalRepository, "insert", fail_insert)
    with pytest.raises(sqlite3.IntegrityError, match="simulated eval failure"):
        repository.complete_chat_turn_with_pedagogy(
            turn.id,
            assistant_message="answer",
            learning_state={"phase": "answer"},
            pedagogy_snapshot={"phase": "answer"},
            route_snapshot={},
            rag_snapshot={},
            operation_id="operation-eval",
            pedagogy_eval_run=run,
        )

    stored_thread = repository.get_chat_thread(thread.id)
    stored_turn = repository.get_chat_turn(turn.id)
    assert stored_thread is not None
    assert stored_thread.learning_state == {"phase": "orientation"}
    assert stored_thread.active_operation_id == "operation-eval"
    assert stored_turn is not None
    assert stored_turn.status == "streaming"
