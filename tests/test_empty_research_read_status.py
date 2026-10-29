"""N16 regression: exhausted reads must not pretend to supply an answer."""

import pytest

from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


@pytest.mark.parametrize(
    ("provider_status", "stop_reason", "body", "expected"),
    [
        ("candidates_only", "source_reading_failed", "", "partial"),
        ("candidates_only", "search_candidates_only", "", "partial"),
        ("found", "sources_read", "Read-backed factual text", "completed"),
        ("empty", "providers_returned_no_results", "", "completed"),
    ],
)
def test_a_finished_research_run_reports_its_evidence_status(
    tmp_path, provider_status, stop_reason, body, expected
):
    repo = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    run = repo.create(WebLookupRun(query="research question", stage="reading"))

    finished = repo.complete(
        run.id,
        items=[],
        source_block=body,
        warnings=["read failed"] if stop_reason == "source_reading_failed" else [],
        provider_status=provider_status,
        stop_reason=stop_reason,
        answer_confidence="none" if not body else "medium",
    )

    assert finished.status == expected
    assert finished.stop_reason == stop_reason
    assert finished.source_block == body
