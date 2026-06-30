from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_web_lookup_service
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class FakeGateway:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def search(self, query: str, *, max_items: int):
        if self.fail:
            raise RuntimeError("provider unavailable")
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
    service = WebLookupService(WebLookupRepository(database), FakeGateway())

    created = service.lookup("durable lookup", max_items=3)
    restored = WebLookupRepository(database).get(created.id)

    assert created.status == "completed"
    assert restored is not None
    assert restored.items[0]["search_excerpt"] == "durable lookup"
    assert restored.source_block
    assert restored.completed_at is not None


def test_web_lookup_run_persists_failure_for_diagnostics(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, FakeGateway(fail=True))

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.lookup("failing lookup", max_items=3)

    runs = repository.list()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].error == "provider unavailable"


def test_web_lookup_run_api_create_get_and_list(runtime_test_context):
    service = WebLookupService(
        runtime_test_context.web_lookup_repository,
        FakeGateway(),
    )
    app.dependency_overrides[get_web_lookup_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/web-lookup-runs",
        json={"query": "API lookup", "max_items": 2},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]

    restored = client.get(f"/web-lookup-runs/{run_id}")
    listed = client.get("/web-lookup-runs")

    assert restored.status_code == 200
    assert restored.json()["status"] == "completed"
    assert restored.json()["items"][0]["search_excerpt"] == "API lookup"
    assert run_id in [run["id"] for run in listed.json()["runs"]]
