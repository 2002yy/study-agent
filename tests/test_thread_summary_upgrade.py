from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.domain.learning_closure import LearningClosureRun
from src.domain.runtime_entities import ChatThread, ChatTurn, utc_now
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.thread_summary_repository import ThreadSummaryRepository


def test_completed_g2_closure_repairs_summary_after_settings_change(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-upgrade-summary"))
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-upgrade-summary",
            thread_id="thread-upgrade-summary",
            status="completed",
            user_message="question",
            assistant_message="answer",
        )
    )
    thread = runtime.get_chat_thread("thread-upgrade-summary")
    assert thread is not None
    source_version = thread.version
    closure_repository = LearningClosureRepository(database)
    closure_repository.create(
        LearningClosureRun(
            id="closure-g2-completed",
            thread_id="thread-upgrade-summary",
            source_thread_version=source_version,
            last_completed_turn_id="turn-upgrade-summary",
            source_hash="legacy-source-hash",
            closure_eligibility="learning_summary",
            status="completed",
            completed_at=utc_now(),
        )
    )
    runtime.update_chat_thread_settings(
        "thread-upgrade-summary", {"selectedRole": "march7"}
    )

    summary = ThreadSummaryRepository(database).get_effective(
        "thread-upgrade-summary"
    )

    assert summary.status == "summarized"
    assert summary.last_completed_turn_id == "turn-upgrade-summary"
    assert summary.current_last_completed_turn_id == "turn-upgrade-summary"
    assert summary.closure_run_id == "closure-g2-completed"
    assert summary.source_thread_version == source_version
    assert summary.can_summarize is False


def test_repeated_summary_completion_keeps_version_and_timestamp(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-idempotent-summary"))
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-idempotent-summary",
            thread_id="thread-idempotent-summary",
            status="completed",
            user_message="question",
            assistant_message="answer",
        )
    )
    thread = runtime.get_chat_thread("thread-idempotent-summary")
    assert thread is not None
    repository = ThreadSummaryRepository(database)

    first = repository.mark_summarized(
        "thread-idempotent-summary",
        source_thread_version=thread.version,
        last_completed_turn_id="turn-idempotent-summary",
        closure_run_id="closure-idempotent-summary",
    )
    repeated = repository.mark_summarized(
        "thread-idempotent-summary",
        source_thread_version=thread.version,
        last_completed_turn_id="turn-idempotent-summary",
        closure_run_id="closure-idempotent-summary",
    )

    assert repeated.version == first.version
    assert repeated.summarized_at == first.summarized_at
    assert repeated.updated_at == first.updated_at


def test_thread_summary_component_initialization_is_concurrency_safe(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-concurrent-summary"))

    def initialize(_: int) -> str:
        repository = ThreadSummaryRepository(database)
        return repository.get_effective("thread-concurrent-summary").status

    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = list(executor.map(initialize, range(4)))

    assert statuses == ["not_summarized"] * 4
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM runtime_component_migrations WHERE component = ?",
            ("thread_summary",),
        ).fetchone()[0]
    assert count == 1
