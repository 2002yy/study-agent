from __future__ import annotations

import json

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.source_assessment import assess_sources, evidence_confidence


def test_source_assessment_requires_a_source_identifier():
    selected, rejected = assess_sources(
        [{"title": "Plausible title without a source"}],
        canonical_query="plausible title",
    )

    assert selected == []
    assert rejected[0]["assessment"]["rejection_reason"] == (
        "missing_source_identifier"
    )


def test_source_assessment_accepts_named_source_without_url_but_does_not_read_it():
    selected, rejected = assess_sources(
        [{"title": "Release note", "source": "vendor documentation"}],
        canonical_query="release note",
    )

    assert rejected == []
    assert selected[0]["assessment"]["selected"] is True
    assert selected[0]["assessment"]["domain"] == "vendor documentation"
    assert selected[0]["assessment"]["worth_reading"] is False


def test_source_assessment_confidence_uses_coverage_not_truth_claims():
    selected, _ = assess_sources(
        [
            {
                "title": "GPT-5.6 Sol official overview",
                "url": "https://example.com/one",
            },
            {
                "title": "GPT-5.6 Sol release details",
                "url": "https://example.net/two",
            },
        ],
        canonical_query="GPT-5.6 Sol",
    )

    assert evidence_confidence(selected) == "high"


def test_repository_normalizes_legacy_raw_selected_sources(tmp_path):
    database = RuntimeDatabase(tmp_path / "legacy-source-shape.db")
    database.initialize()
    raw_item = {
        "title": "Legacy result",
        "url": "https://example.com/legacy",
    }
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO web_lookup_runs(
                id, query, stage, status, research_context, query_attempts,
                selected_sources, rejected_sources, provider_status,
                stop_reason, answer_confidence, items, source_block,
                warnings, error, version, created_at, updated_at, completed_at
            ) VALUES (
                'web_lookup_legacy_shape', 'legacy result', 'completed',
                'completed', '{}', '[]', ?, '[]', 'found',
                'direct_results_found', '', ?, '', '[]', '', 1,
                '2026-07-01T00:00:00+00:00',
                '2026-07-01T00:00:00+00:00',
                '2026-07-01T00:00:00+00:00'
            )
            """,
            (json.dumps([raw_item]), json.dumps([raw_item])),
        )

    run = WebLookupRepository(database).get("web_lookup_legacy_shape")

    assert run is not None
    assert run.selected_sources[0]["item"] == raw_item
    assert run.selected_sources[0]["assessment"]["selected"] is True
    assert run.rejected_sources == []
