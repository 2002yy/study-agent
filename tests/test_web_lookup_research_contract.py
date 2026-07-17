from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

import pytest

from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import (
    MIGRATIONS,
    RuntimeDatabase,
    SCHEMA_VERSION,
    _migration_statements,
    apply_migrations,
    schema_version,
)
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_contract import (
    build_research_context,
    failed_attempt,
    stop_reason,
    successful_attempt,
)


class FakeGateway:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict]:
        self.calls.append(query)
        response = self.responses.get(query, [])
        if isinstance(response, Exception):
            raise response
        return list(response)[:max_items]

    def warnings(self) -> list[dict]:
        return []


def _service(tmp_path, gateway: FakeGateway) -> tuple[WebLookupService, WebLookupRepository]:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    return WebLookupService(repository, gateway), repository


def _apply_migrations_before(connection: sqlite3.Connection, target_version: int) -> None:
    for version, sql in MIGRATIONS:
        if version >= target_version:
            break
        for statement in _migration_statements(sql):
            connection.execute(statement)
        connection.execute(
            "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES('schema_version', ?)",
            (str(version),),
        )
    connection.commit()


def _insert_legacy_web_lookup(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    items: str = "[]",
    completed_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO web_lookup_runs(
            id, query, status, items, source_block, warnings, error,
            version, created_at, updated_at, completed_at
        ) VALUES (?, 'legacy query', ?, ?, '', '[]', '', 1, ?, ?, ?)
        """,
        (
            run_id,
            status,
            items,
            "2026-07-01T00:00:00+00:00",
            "2026-07-01T00:00:00+00:00",
            completed_at,
        ),
    )
    connection.commit()


def test_research_context_preserves_raw_query_and_normalizes_compact_model_name():
    context = build_research_context(
        "联网看看gpt5.6sol",
        now=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )

    assert context.raw_query == "联网看看gpt5.6sol"
    assert context.canonical_query == "GPT-5.6 Sol"
    assert context.query_variants[0] == "GPT-5.6 Sol"
    assert "gpt5.6sol" in context.query_variants
    assert context.as_of_date == "2026-07-13"
    assert len(context.query_variants) <= 3


def test_direct_lookup_persists_bounded_attempts_and_assessed_sources(tmp_path):
    gateway = FakeGateway(
        {
            "GPT-5.6 Sol": [],
            "gpt5.6sol": [
                {
                    "title": "GPT-5.6 Sol release details",
                    "link": "https://example.com/result",
                    "source": "example.com",
                }
            ],
        }
    )
    service, repository = _service(tmp_path, gateway)

    run = service.lookup("联网看看gpt5.6sol", max_items=5)
    restored = repository.get(run.id)

    assert gateway.calls == ["GPT-5.6 Sol", "gpt5.6sol"]
    assert run.stage == "completed"
    assert run.status == "completed"
    assert run.research_context["canonical_query"] == "GPT-5.6 Sol"
    assert [attempt["status"] for attempt in run.query_attempts] == ["empty", "found"]
    assert run.provider_status == "found"
    assert run.stop_reason == "direct_results_found"
    assert run.answer_confidence == "medium"
    assert run.selected_sources[0]["item"] == run.items[0]
    assert run.selected_sources[0]["assessment"]["selected"] is True
    assert run.selected_sources[0]["assessment"]["directness"] == "direct_title"
    assert run.rejected_sources == []
    assert run.warnings == []
    assert restored == run


def test_lookup_rejects_invalid_and_duplicate_sources_before_citation(tmp_path):
    duplicate = {
        "title": "GPT-5.6 Sol overview",
        "link": "https://example.com/model",
    }
    gateway = FakeGateway(
        {
            "GPT-5.6 Sol": [
                duplicate,
                dict(duplicate),
                {"title": "", "link": ""},
                {"title": "Bad URL", "link": "javascript:alert(1)"},
            ]
        }
    )
    service, _ = _service(tmp_path, gateway)

    run = service.lookup("联网看看gpt5.6sol", max_items=8)

    assert len(run.items) == 1
    assert len(run.selected_sources) == 1
    reasons = {
        record["assessment"]["rejection_reason"]
        for record in run.rejected_sources
    }
    assert reasons == {"duplicate", "missing_title_and_url", "invalid_url"}
    assert run.stop_reason == "direct_results_found"


def test_empty_results_remain_empty_evidence_not_confirmed_absence(tmp_path):
    gateway = FakeGateway({})
    service, repository = _service(tmp_path, gateway)

    run = service.lookup("unknown-new-entity", max_items=5)
    restored = repository.get(run.id)

    assert run.stage == "completed"
    assert run.status == "completed"
    assert run.items == []
    assert run.selected_sources == []
    assert run.provider_status == "empty"
    assert run.stop_reason == "providers_returned_no_results"
    assert run.answer_confidence == "none"
    assert "confirmed_absence" not in run.stop_reason
    assert restored == run


def test_all_provider_failures_persist_failed_attempts(tmp_path):
    context = build_research_context("联网看看gpt5.6sol")
    gateway = FakeGateway(
        {
            query: RuntimeError(f"provider unavailable for {query}")
            for query in context.query_variants
        }
    )
    service, repository = _service(tmp_path, gateway)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.lookup("联网看看gpt5.6sol", max_items=5)

    runs = repository.list()
    assert len(runs) == 1
    assert runs[0].stage == "failed"
    assert runs[0].status == "failed"
    assert runs[0].provider_status == "provider_failed"
    assert runs[0].stop_reason == "providers_failed"
    assert all(
        attempt["status"] == "provider_failed" for attempt in runs[0].query_attempts
    )
    assert len(gateway.calls) == len(context.query_variants)


def test_repository_stage_transition_is_compare_and_set(tmp_path):
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "stage.db"))
    run = repository.create(WebLookupRun(query="x", stage="searching"))

    transitioned = repository.transition_stage(
        run.id,
        expected_stage="searching",
        stage="assessing",
    )

    assert transitioned.stage == "assessing"
    assert transitioned.version == run.version + 1
    with pytest.raises(ValueError, match="not transitionable"):
        repository.transition_stage(
            run.id,
            expected_stage="searching",
            stage="assessing",
        )


def test_schema_15_backfills_legacy_completed_web_lookup(tmp_path):
    connection = sqlite3.connect(tmp_path / "legacy-completed.db")
    connection.row_factory = sqlite3.Row
    _apply_migrations_before(connection, 14)
    _insert_legacy_web_lookup(
        connection,
        run_id="web_lookup_legacy_completed",
        status="completed",
        items='[{"title": "Legacy"}]',
        completed_at="2026-07-01T00:00:00+00:00",
    )

    apply_migrations(connection)
    row = connection.execute(
        "SELECT * FROM web_lookup_runs WHERE id = 'web_lookup_legacy_completed'"
    ).fetchone()

    assert schema_version(connection) == SCHEMA_VERSION
    assert row["stage"] == "completed"
    assert row["provider_status"] == "found"
    assert row["stop_reason"] == "direct_results_found"
    assert row["selected_sources"] == row["items"]
    connection.close()


def test_schema_15_marks_legacy_running_lookup_as_interrupted_not_empty(tmp_path):
    connection = sqlite3.connect(tmp_path / "legacy-running.db")
    connection.row_factory = sqlite3.Row
    _apply_migrations_before(connection, 14)
    _insert_legacy_web_lookup(
        connection,
        run_id="web_lookup_legacy_running",
        status="running",
    )

    apply_migrations(connection)
    row = connection.execute(
        "SELECT * FROM web_lookup_runs WHERE id = 'web_lookup_legacy_running'"
    ).fetchone()

    assert schema_version(connection) == SCHEMA_VERSION
    assert row["stage"] == "failed"
    assert row["status"] == "failed"
    assert row["provider_status"] == "unknown"
    assert row["stop_reason"] == "legacy_run_interrupted"
    assert "interrupted" in row["error"].lower()
    assert row["completed_at"] == row["updated_at"]
    connection.close()


def test_stop_reason_distinguishes_found_empty_and_failed_attempts():
    assert stop_reason([successful_attempt("a", 1)]) == "direct_results_found"
    assert stop_reason([successful_attempt("a", 0)]) == "providers_returned_no_results"
    assert stop_reason([failed_attempt("a", "timeout")]) == "providers_failed"
