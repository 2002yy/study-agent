from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
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


def test_direct_lookup_tries_bounded_variants_until_results_are_found(tmp_path):
    gateway = FakeGateway(
        {
            "GPT-5.6 Sol": [],
            "gpt5.6sol": [
                {
                    "title": "Result",
                    "link": "https://example.com/result",
                    "source": "example.com",
                }
            ],
        }
    )
    service, repository = _service(tmp_path, gateway)

    run = service.lookup("联网看看gpt5.6sol", max_items=5)

    assert gateway.calls == ["GPT-5.6 Sol", "gpt5.6sol"]
    assert run.status == "completed"
    assert len(run.items) == 1
    assert repository.get(run.id) == run
    assert any("stop_reason=direct_results_found" in warning for warning in run.warnings)


def test_empty_results_remain_empty_evidence_not_confirmed_absence(tmp_path):
    gateway = FakeGateway({})
    service, _ = _service(tmp_path, gateway)

    run = service.lookup("unknown-new-entity", max_items=5)

    assert run.status == "completed"
    assert run.items == []
    trace = next(warning for warning in run.warnings if warning.startswith("research trace:"))
    assert "stop_reason=providers_returned_no_results" in trace
    assert "confirmed_absence" not in trace


def test_all_provider_failures_fail_the_run_after_bounded_attempts(tmp_path):
    context = build_research_context("联网看看gpt5.6sol")
    gateway = FakeGateway(
        {query: RuntimeError(f"provider unavailable for {query}") for query in context.query_variants}
    )
    service, repository = _service(tmp_path, gateway)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.lookup("联网看看gpt5.6sol", max_items=5)

    runs = repository.list()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert len(gateway.calls) == len(context.query_variants)


def test_stop_reason_distinguishes_found_empty_and_failed_attempts():
    assert stop_reason([successful_attempt("a", 1)]) == "direct_results_found"
    assert stop_reason([successful_attempt("a", 0)]) == "providers_returned_no_results"
    assert stop_reason([failed_attempt("a", "timeout")]) == "providers_failed"
