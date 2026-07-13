from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_web_lookup_service
from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class FakeGateway:
    def __init__(self, responses=None):
        self.responses = list(responses or ["success"])
        self.queries: list[str] = []

    def search(self, query: str, *, max_items: int):
        self.queries.append(query)
        response = self.responses.pop(0) if self.responses else "success"
        if isinstance(response, Exception):
            raise response
        if response == "empty":
            return []
        return [
            {
                "title": "Result",
                "url": "https://example.com/result",
                "source": "Example",
                "search_excerpt": query,
            }
        ][:max_items]

    def warnings(self):
        return []


def test_web_lookup_run_persists_and_restores_after_repository_restart(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    gateway = FakeGateway()
    service = WebLookupService(WebLookupRepository(database), gateway)

    planned = service.create("gpt5.6sol 最新进展", max_items=3)
    assert planned.status == "pending"
    assert planned.stage == "planned"
    assert planned.query_plan["canonical_query"] == "GPT-5.6 Sol 最新进展"

    restored_service = WebLookupService(WebLookupRepository(database), gateway)
    completed = restored_service.search(planned.id)
    restored = WebLookupRepository(database).get(planned.id)

    assert completed.status == "completed"
    assert restored is not None
    assert restored.items[0]["search_excerpt"] == "GPT-5.6 Sol 最新进展"
    assert restored.source_block
    assert restored.completed_at is not None
    assert restored.attempts[0]["queries"] == ["GPT-5.6 Sol 最新进展"]
    assert restored.attempts[0]["result_count"] == 1


def test_web_lookup_run_persists_failure_then_retries_after_restart(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    failing_gateway = FakeGateway([RuntimeError("provider unavailable")])
    service = WebLookupService(WebLookupRepository(database), failing_gateway)
    planned = service.create("failing lookup", max_items=3)

    failed = service.search(planned.id, raise_on_error=False)

    assert failed.status == "failed"
    assert failed.stage == "failed"
    assert failed.error == "provider unavailable"
    assert failed.attempts[0]["status"] == "failed"

    restored_service = WebLookupService(
        WebLookupRepository(database),
        FakeGateway(["success"]),
    )
    completed = restored_service.retry(planned.id)

    assert completed.status == "completed"
    assert len(completed.attempts) == 2
    assert completed.attempts[1]["attempt"] == 2
    assert completed.error == ""


def test_web_lookup_run_empty_result_is_retryable_not_nonexistence(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    service = WebLookupService(
        WebLookupRepository(database),
        FakeGateway(["empty"] * 8),
    )
    planned = service.create("unknown compact term", max_items=3)

    empty = service.search(planned.id)

    assert empty.status == "empty"
    assert empty.stage == "empty"
    assert empty.empty_reason == "providers_returned_no_results"
    assert empty.error == ""
    assert empty.attempts[0]["status"] == "empty"
    assert "nonexistent" not in str(empty.attempts).lower()


def test_stale_search_operation_can_be_recovered_without_old_owner_writeback(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    run = repository.create(WebLookupRun(query="recover me"))
    repository.begin_search(run.id, operation_id="op_old")
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET active_operation_started_at = ? WHERE id = ?",
            (stale, run.id),
        )

    recovered = repository.begin_search(
        run.id,
        operation_id="op_new",
        stale_after_seconds=60,
    )

    assert recovered.active_operation_id == "op_new"
    with pytest.raises(ValueError, match="lost ownership"):
        repository.complete_search(
            run.id,
            operation_id="op_old",
            items=[],
            source_block="",
            warnings=[],
            attempts=[],
            empty_reason="providers_returned_no_results",
        )


def test_one_shot_lookup_compatibility_still_raises_and_persists_failure(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(
        repository,
        FakeGateway([RuntimeError("provider unavailable")]),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.lookup("failing lookup", max_items=3)

    runs = repository.list()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].attempts[0]["error"] == "provider unavailable"


def test_research_run_api_create_search_get_list_and_retry(runtime_test_context):
    gateway = FakeGateway(["empty"] * 8 + ["success"])
    service = WebLookupService(
        runtime_test_context.web_lookup_repository,
        gateway,
    )
    app.dependency_overrides[get_web_lookup_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/research-runs",
        json={"query": "API lookup", "max_items": 2},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    searched = client.post(f"/research-runs/{run_id}/search")
    assert searched.status_code == 200
    assert searched.json()["status"] == "empty"
    assert searched.json()["attempts"][0]["attempt"] == 1

    retried = client.post(f"/research-runs/{run_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "completed"
    assert retried.json()["attempts"][1]["attempt"] == 2

    restored = client.get(f"/research-runs/{run_id}")
    listed = client.get("/research-runs")

    assert restored.status_code == 200
    assert restored.json()["items"][0]["search_excerpt"] == "API lookup"
    assert run_id in [run["id"] for run in listed.json()["runs"]]
