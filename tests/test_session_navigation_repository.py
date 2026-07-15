from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.domain.runtime_entities import ChatThread
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.session_navigation_repository import SessionNavigationRepository


def test_manual_title_write_is_idempotent_and_separate_from_thread_version(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-title-meta"))
    thread_before = runtime.get_chat_thread("thread-title-meta")
    assert thread_before is not None
    repository = SessionNavigationRepository(database)

    first = repository.set_manual_title("thread-title-meta", "  Java 并发复习  ")
    repeated = repository.set_manual_title("thread-title-meta", "Java 并发复习")
    thread_after = runtime.get_chat_thread("thread-title-meta")

    assert first.manual_title == "Java 并发复习"
    assert repeated.version == first.version
    assert repeated.updated_at == first.updated_at
    assert thread_after is not None
    assert thread_after.version == thread_before.version


def test_session_navigation_component_initialization_is_concurrency_safe(tmp_path: Path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-navigation-init"))

    def initialize(_: int) -> str:
        return SessionNavigationRepository(database).get_title(
            "thread-navigation-init"
        ).manual_title

    with ThreadPoolExecutor(max_workers=4) as executor:
        titles = list(executor.map(initialize, range(4)))

    assert titles == [""] * 4
    with database.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM runtime_component_migrations WHERE component = ?",
            ("session_navigation",),
        ).fetchone()[0]
    assert count == 1
