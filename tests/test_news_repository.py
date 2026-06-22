from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from src.domain.runtime_entities import NewsRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.news_repository import NewsRepository


def test_news_stage_operation_has_single_owner(tmp_path):
    repository = NewsRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    run = repository.create(NewsRun(id="news-concurrent", query="AI"))
    barrier = Barrier(2)

    def acquire(operation_id: str) -> str:
        barrier.wait(timeout=5)
        try:
            repository.acquire_operation(
                run.id, operation_id, expected_stages=("created",)
            )
            return operation_id
        except ValueError:
            return ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = list(executor.map(acquire, ["operation-a", "operation-b"]))

    assert sum(bool(item) for item in winners) == 1
    assert repository.get(run.id).active_operation_id in winners


def test_news_stage_cas_rejects_wrong_stage_and_stale_owner(tmp_path):
    repository = NewsRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    run = repository.create(NewsRun(id="news-cas", query="AI"))
    repository.acquire_operation(run.id, "search-owner", expected_stages=("created",))
    repository.complete_operation(
        run.id, "search-owner", stage="searched", items=[{"title": "A"}]
    )

    try:
        repository.acquire_operation(run.id, "digest-early", expected_stages=("enriched",))
        raise AssertionError("wrong stage must not acquire")
    except ValueError:
        pass

    repository.acquire_operation(run.id, "digest-owner", expected_stages=("searched",))
    try:
        repository.complete_operation(run.id, "stale-owner", stage="digested")
        raise AssertionError("stale owner must not settle")
    except ValueError:
        pass
    assert repository.get(run.id).active_operation_id == "digest-owner"


def test_stale_news_operation_recovers_without_advancing_stage(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = NewsRepository(database)
    run = repository.create(NewsRun(id="news-stale", query="AI", stage="searched"))
    repository.acquire_operation(run.id, "operation-old", expected_stages=("searched",))
    with database.connect() as connection:
        connection.execute(
            "UPDATE news_runs SET active_operation_started_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", run.id),
        )

    recovered = NewsRepository(database).get(run.id)

    assert recovered.stage == "searched"
    assert recovered.status == "failed"
    assert recovered.active_operation_id is None
    assert recovered.error == "stale operation recovered"
