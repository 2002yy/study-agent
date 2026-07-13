from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_web_lookup_service
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class FakeResearchGateway:
    def __init__(
        self,
        *,
        fail_search: bool = False,
        cancel_repository: WebLookupRepository | None = None,
        cancel_run_id: str = "",
    ) -> None:
        self.fail_search = fail_search
        self.cancel_repository = cancel_repository
        self.cancel_run_id = cancel_run_id
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict]:
        self.search_calls.append(query)
        if self.fail_search:
            raise RuntimeError("provider unavailable")
        return [
            {
                "title": f"{query} official result",
                "url": "https://example.com/source",
                "link": "https://example.com/source",
                "source": "example.com",
                "snippet": f"Primary material about {query}",
                "search_excerpt": f"Primary material about {query}",
            }
        ][:max_items]

    def read(self, url: str, *, max_chars: int = 6000) -> dict:
        self.read_calls.append(url)
        if self.cancel_repository is not None and self.cancel_run_id:
            self.cancel_repository.request_cancel(self.cancel_run_id)
            self.cancel_repository = None
        return {
            "ok": True,
            "kind": "web_page",
            "url": url,
            "method": "fake_reader",
            "content": "verified source text"[:max_chars],
        }

    def warnings(self) -> list[dict[str, str]]:
        return []


def _stack(tmp_path, gateway: FakeResearchGateway):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    return database, repository, WebLookupService(repository, gateway)


def test_create_persists_planned_run_before_provider_access(tmp_path):
    gateway = FakeResearchGateway()
    _, repository, service = _stack(tmp_path, gateway)

    run = service.create("resumable lookup", max_items=4)
    restored = repository.get(run.id)

    assert run.status == "pending"
    assert run.stage == "planned"
    assert run.max_items == 4
    assert gateway.search_calls == []
    assert restored == run


def test_failed_search_retries_after_repository_restart(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    first_repository = WebLookupRepository(database)
    first = WebLookupService(
        first_repository,
        FakeResearchGateway(fail_search=True),
    )
    planned = first.create("retry lookup", max_items=3)

    failed = first.execute(planned.id)

    assert failed.status == "failed"
    assert failed.stage == "failed"
    assert failed.provider_status == "provider_failed"
    first_attempt_count = len(failed.query_attempts)
    assert first_attempt_count >= 1

    second_gateway = FakeResearchGateway()
    second = WebLookupService(WebLookupRepository(database), second_gateway)
    completed = second.retry(planned.id)

    assert completed.status == "completed"
    assert completed.stage == "completed"
    assert completed.provider_status == "found"
    assert len(completed.query_attempts) > first_attempt_count
    assert second_gateway.search_calls
    assert completed.research_context["run_attempt"] == 2


def test_cancel_during_read_checkpoints_result_and_resume_skips_completed_work(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    cancelling_gateway = FakeResearchGateway(cancel_repository=repository)
    service = WebLookupService(repository, cancelling_gateway)
    planned = service.create("cancel lookup", max_items=3)
    cancelling_gateway.cancel_run_id = planned.id

    cancelled = service.execute(planned.id)

    assert cancelled.status == "cancelled"
    assert cancelled.stage == "cancelled"
    assert cancelled.stop_reason == "user_cancelled"
    assert cancelled.query_attempts
    assert cancelled.selected_sources[0]["read"]["status"] == "read"

    resume_gateway = FakeResearchGateway()
    resumed = WebLookupService(
        WebLookupRepository(database),
        resume_gateway,
    ).resume(planned.id)

    assert resumed.status == "completed"
    assert resumed.provider_status == "found"
    assert resume_gateway.search_calls == []
    assert resume_gateway.read_calls == []
    assert resumed.selected_sources[0]["read"]["content"] == "verified source text"


def test_stale_owner_cannot_write_after_new_operation_takes_over(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, FakeResearchGateway())
    planned = service.create("ownership lookup", max_items=3)
    old = repository.begin_operation(
        planned.id,
        operation_id="op_old",
        stage="searching",
    )
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    context = dict(old.research_context)
    operation = dict(context.get("operation") or {})
    operation["active_operation_started_at"] = stale
    context["operation"] = operation
    with database.connect() as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (json.dumps(context), planned.id),
        )

    current = repository.begin_operation(
        planned.id,
        operation_id="op_new",
        stage="searching",
        stale_after_seconds=60,
    )

    assert current.active_operation_id == "op_new"
    with pytest.raises(ValueError, match="lost ownership"):
        repository.checkpoint(
            planned.id,
            operation_id="op_old",
            research_context=current.research_context,
            query_attempts=[],
            selected_sources=[],
            rejected_sources=[],
            items=[],
            warnings=[],
        )


def test_research_run_api_create_execute_cancel_and_resume(runtime_test_context):
    repository = runtime_test_context.web_lookup_repository
    gateway = FakeResearchGateway()
    service = WebLookupService(repository, gateway)
    app.dependency_overrides[get_web_lookup_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/research-runs",
        json={"query": "API research", "max_items": 2},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    completed = client.post(f"/research-runs/{run_id}/search")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["query_attempts"]

    pending = client.post(
        "/research-runs",
        json={"query": "cancel before start", "max_items": 2},
    )
    pending_id = pending.json()["id"]
    cancelled = client.post(f"/research-runs/{pending_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    resumed = client.post(f"/research-runs/{pending_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
