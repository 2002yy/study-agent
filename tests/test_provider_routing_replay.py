"""Offline contracts for the provider-routing replay.

The capture is synthetic: these tests check strategy wiring, the gate/evaluation
separation and the input binding, not any provider's quality. No network or model
call happens here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_provider_routing_replay as replay_mod
from tools.run_provider_routing_replay import _query_fingerprint, replay, verdict

CASE_X = {
    "id": "X1",
    "question": "星铁 千冶刃 遗器 配装",
    "query": "星铁 千冶刃 遗器",
    "anchors": ["星铁", "千冶", "遗器"],
    "focus": ["配装"],
}
CASE_Y = {
    "id": "Y1",
    "question": "Python 稳定版本",
    "query": "Python latest stable version",
    "anchors": ["python"],
    "focus": ["stable", "version"],
}

GUIDE = {
    "title": "星铁 千冶刃 遗器 配装攻略",
    "url": "https://example.org/guide",
    "source": "DuckDuckGo",
    "snippet": "",
    "snippet_chars": 0,
}
DICTIONARY = {
    "title": "千（汉语汉字）_百度百科",
    "url": "https://example.org/dict",
    "source": "SearXNG/bing",
    "snippet": "",
    "snippet_chars": 0,
}
DICTIONARY_2 = {
    "title": "千 qiān - 汉典",
    "url": "https://example.org/dict2",
    "source": "SearXNG/bing",
    "snippet": "",
    "snippet_chars": 0,
}
DICTIONARY_3 = {
    "title": "《千》的拼音,千字的意思",
    "url": "https://example.org/dict3",
    "source": "SearXNG/bing",
    "snippet": "",
    "snippet_chars": 0,
}
DICTIONARY_4 = {
    "title": "星（汉语文字）_百度百科",
    "url": "https://example.org/dict4",
    "source": "SearXNG/bing",
    "snippet": "",
    "snippet_chars": 0,
}
PYTHON_RELEASE = {
    "title": "Python latest stable version",
    "url": "https://example.org/python",
    "source": "SearXNG/bing",
    "snippet": "",
    "snippet_chars": 0,
}


def _queries(tmp_path: Path, cases: list[dict] | None = None) -> Path:
    document = {
        "schema_version": "provider-routing-queries-v1",
        "cases": cases or [CASE_X, CASE_Y],
    }
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _capture(tmp_path: Path, *, case_ids: list[str] | None = None) -> Path:
    document = {
        "schema_version": "provider-routing-capture-v1",
        "query_set_version": "provider-routing-queries-v1",
        "query_set_fingerprint": _query_fingerprint([CASE_X, CASE_Y]),
        "case_ids": case_ids or ["X1", "Y1"],
        "limit": 6,
        "cases": [
            {
                "id": "X1",
                "query": CASE_X["query"],
                "providers": {
                    "bing": {
                        "status": "ok",
                        "elapsed": 0.4,
                        "provider_errors": [],
                        "results": [DICTIONARY, DICTIONARY_2, DICTIONARY_3, DICTIONARY_4],
                    },
                    "ddg": {"status": "ok", "elapsed": 3.0, "provider_errors": [], "results": [GUIDE]},
                },
            },
            {
                "id": "Y1",
                "query": CASE_Y["query"],
                "providers": {
                    "bing": {"status": "ok", "elapsed": 0.4, "provider_errors": [], "results": [PYTHON_RELEASE]},
                    "ddg": {"status": "ok", "elapsed": 3.0, "provider_errors": [], "results": [DICTIONARY]},
                },
            },
        ],
    }
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def replay_doc(tmp_path, monkeypatch):
    queries = _queries(tmp_path)
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", queries)

    def assessor(results, *, canonical_query):
        records = []
        for item in results:
            # "Python" pages look strong to the assessor; everything else weak.
            score = 0.9 if "python" in item["title"].casefold() else 0.1
            records.append({"item": item, "assessment": {"relevance": score}})
        return records, []

    monkeypatch.setattr("src.web.source_assessment.assess_sources", assessor)
    return replay(capture_path=_capture(tmp_path), output=tmp_path / "replay.json", limit=6)


def test_single_character_anchors_never_count_as_relevance():
    case = {"anchors": ["星"], "focus": []}
    assert verdict({"title": "星（汉语文字）_百度百科", "url": "u"}, case)["relevant"] is False


def test_e0_stops_at_the_first_provider_with_results(replay_doc):
    row = replay_doc["cases"][0]["strategies"]["E0"]

    assert row["provider_calls"] == 1
    assert row["hit_at_3"] is False


def test_e1_merges_without_ranking_so_provider_order_decides(replay_doc):
    row = replay_doc["cases"][0]["strategies"]["E1"]

    assert row["provider_calls"] == 2
    assert row["hit_at_3"] is False


def test_e2_ranks_with_the_assessor_not_with_the_evaluation_rule(replay_doc, tmp_path, monkeypatch):
    def reverse_assessor(results, *, canonical_query):
        records = [
            {"item": item, "assessment": {"relevance": 1.0 - index * 0.1}}
            for index, item in enumerate(reversed(results))
        ]
        return records, []

    monkeypatch.setattr("src.web.source_assessment.assess_sources", reverse_assessor)
    document = replay(
        capture_path=_capture(tmp_path), output=tmp_path / "replay2.json", limit=6
    )

    assert document["cases"][0]["strategies"]["E2"]["hit_at_3"] is True


def test_gate_uses_the_assessor_and_never_the_evaluation_rule(monkeypatch):
    # Judged by the evaluation rule this page is irrelevant, yet the assessor is
    # confident: the gate must follow the assessor, because that is what survives
    # in production.
    monkeypatch.setattr(
        "src.web.source_assessment.assess_sources",
        lambda results, *, canonical_query: (
            [{"item": item, "assessment": {"relevance": 0.8}} for item in results],
            [],
        ),
    )
    gate = replay_mod._gate_sufficient([DICTIONARY], CASE_X, strategy="assessor")

    assert verdict(DICTIONARY, CASE_X)["relevant"] is False
    assert gate["sufficient"] is True


def test_gate_stays_closed_when_the_assessor_is_not_confident(monkeypatch):
    monkeypatch.setattr(
        "src.web.source_assessment.assess_sources",
        lambda results, *, canonical_query: (
            [{"item": item, "assessment": {"relevance": 0.05}} for item in results],
            [],
        ),
    )

    gate = replay_mod._gate_sufficient([GUIDE], CASE_X, strategy="assessor")
    assert gate["sufficient"] is False


def test_ngram_gate_uses_only_the_query_text(monkeypatch):
    # The guide covers query bigrams; the gate must accept it without touching
    # the curated anchors used for evaluation.
    monkeypatch.setattr(
        "src.web.source_assessment.assess_sources",
        lambda results, *, canonical_query: ([], []),
    )

    gate = replay_mod._gate_sufficient([GUIDE], CASE_X, strategy="ngram")
    assert gate["sufficient"] is True
    assert gate["best_overlap"] >= 2


def test_e3_calls_the_next_provider_only_when_the_gate_is_open(replay_doc):
    first, second = replay_doc["cases"]

    assert first["strategies"]["E3_assessor"]["triggered_extra_provider"] is True
    assert first["strategies"]["E3_assessor"]["provider_calls"] == 2
    assert second["strategies"]["E3_assessor"]["triggered_extra_provider"] is False
    assert second["strategies"]["E3_assessor"]["provider_calls"] == 1
    # The n-gram gate also stops for Y1 (its result covers query bigrams) but
    # still has to call the second provider for X1, whose E0 results are junk.
    assert first["strategies"]["E3_ngram"]["triggered_extra_provider"] is True
    assert second["strategies"]["E3_ngram"]["triggered_extra_provider"] is False
    assert replay_doc["summary"]["gates"]["assessor"]["correct_skips"] == 1


def test_capture_and_query_set_must_match(tmp_path, monkeypatch):
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", _queries(tmp_path))

    with pytest.raises(ValueError, match="capture_case_ids_mismatch"):
        replay(
            capture_path=_capture(tmp_path, case_ids=["X1"]),
            output=tmp_path / "replay.json",
            limit=6,
        )


def test_changed_query_text_is_rejected_even_with_the_same_ids(tmp_path, monkeypatch):
    changed = [dict(CASE_X, query="星铁 千冶刃 遗器 配装 攻略"), CASE_Y]
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", _queries(tmp_path, changed))

    with pytest.raises(ValueError, match="capture_query_set_fingerprint_mismatch"):
        replay(capture_path=_capture(tmp_path), output=tmp_path / "r.json", limit=6)


def test_changed_evaluation_anchors_are_rejected(tmp_path, monkeypatch):
    changed = [dict(CASE_X, anchors=[*CASE_X["anchors"], "配装"]), CASE_Y]
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", _queries(tmp_path, changed))

    with pytest.raises(ValueError, match="capture_query_set_fingerprint_mismatch"):
        replay(capture_path=_capture(tmp_path), output=tmp_path / "r.json", limit=6)


def test_replay_uses_the_queries_path_it_is_given(tmp_path):
    queries = _queries(tmp_path)

    document = replay(
        capture_path=_capture(tmp_path),
        output=tmp_path / "r.json",
        limit=6,
        queries_path=queries,
    )

    assert document["cases"]
    assert document["capture"].endswith("capture.json")


def test_metrics_always_use_a_six_result_window(tmp_path, monkeypatch):
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", _queries(tmp_path))

    with pytest.raises(ValueError, match="limit_below_evaluation_window"):
        replay(capture_path=_capture(tmp_path), output=tmp_path / "r.json", limit=3)


def test_summary_separates_gate_quality_from_e3_quality(replay_doc):
    summary = replay_doc["summary"]

    assert summary["gates"]["assessor"]["triggered"] == 1
    assert summary["gates"]["assessor"]["skipped"] == 1
    assert summary["gates"]["ngram"]["skipped"] == 1
    assert summary["gates"]["ngram"]["correct_skips"] == 1
    for name in ("E0", "E1", "E2", "E3_assessor", "E3_ngram"):
        assert "latency_p50" in summary["strategies"][name]
