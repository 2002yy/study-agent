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

    # Search candidates are not read-backed evidence.
    assert evidence_confidence(selected) == "none"
    read_backed = [{**record, "read": {"status": "read"}} for record in selected]
    assert evidence_confidence(read_backed) == "high"


def test_unread_candidates_cannot_inflate_one_unrelated_read():
    selected, _ = assess_sources(
        [
            {"title": "星（汉语文字）", "url": "https://example.org/dictionary"},
            {"title": "千冶·刃 遗器 黄泉队 攻略", "url": "https://example.org/guide"},
        ],
        canonical_query="星铁 千冶·刃 遗器 推荐 黄泉队",
    )
    selected[0]["read"] = {"status": "read", "content": "星的笔顺"}
    assert evidence_confidence(selected) == "low"
    selected[1]["read"] = {"status": "read", "content": "千冶·刃 遗器"}
    assert evidence_confidence(selected) == "medium"


def test_cjk_dictionary_page_no_longer_looks_relevant_to_an_entity_query():
    """One shared character must not make a dictionary entry worth reading.

    This is the Search-1 failure: the Baidu entry for 星 was delivered and read
    for "星铁 千冶·刃 遗器", because single-character overlap counted as context.
    """

    selected, _ = assess_sources(
        [
            {
                "title": "星（汉语文字）_百度百科",
                "url": "https://baike.baidu.com/item/%E6%98%9F/1586",
            }
        ],
        canonical_query="星铁 千冶·刃 遗器 推荐 黄泉队",
    )

    assessment = selected[0]["assessment"]
    assert assessment["directness"] == "unmatched"
    assert assessment["relevance"] < 0.2
    # Lexical relevance is a signal, not a veto on reading a valid URL.
    assert assessment["worth_reading"] is True


def test_cjk_bigram_overlap_still_marks_the_matching_guide_relevant():
    selected, _ = assess_sources(
        [
            {
                "title": "星铁 千冶刃 遗器 光锥 搭配推荐",
                "url": "https://example.org/guide",
                "snippet": "千冶刃加入黄泉队后的遗器与光锥选择。",
            }
        ],
        canonical_query="星铁 千冶·刃 遗器 推荐 黄泉队",
    )

    assessment = selected[0]["assessment"]
    assert assessment["directness"] in {"contextual", "direct_title", "direct_snippet"}
    assert assessment["relevance"] >= 0.7
    assert assessment["worth_reading"] is True


def test_a_single_cjk_character_query_still_matches():
    selected, _ = assess_sources(
        [{"title": "刃", "url": "https://example.org/blade"}],
        canonical_query="刃",
    )

    assert selected[0]["assessment"]["directness"] == "direct_title"


def test_english_function_words_do_not_make_a_page_relevant():
    selected, _ = assess_sources(
        [{"title": "How to do it: the guide for you", "url": "https://example.org/filler"}],
        canonical_query="How to configure Nginx proxy_cache expiration",
    )

    assessment = selected[0]["assessment"]
    assert assessment["directness"] == "unmatched"
    assert assessment["relevance"] < 0.2
    # Lexical relevance is a signal, not a veto on reading a valid URL.
    assert assessment["worth_reading"] is True


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
