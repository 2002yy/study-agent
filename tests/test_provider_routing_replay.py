"""Offline contracts for the provider-routing replay.

The capture is synthetic: these tests check the strategies' wiring, not the
quality of any provider. No network and no model call happens here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import run_provider_routing_replay as replay_mod
from tools.run_provider_routing_replay import replay, verdict

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
    "snippet_chars": 0,
}
DICTIONARY = {
    "title": "千（汉语汉字）_百度百科",
    "url": "https://example.org/dict",
    "source": "SearXNG/bing",
    "snippet_chars": 0,
}
DICTIONARY_2 = {
    "title": "千 qiān - 汉典",
    "url": "https://example.org/dict2",
    "source": "SearXNG/bing",
    "snippet_chars": 0,
}
DICTIONARY_3 = {
    "title": "《千》的拼音,千字的意思",
    "url": "https://example.org/dict3",
    "source": "SearXNG/bing",
    "snippet_chars": 0,
}
DICTIONARY_4 = {
    "title": "星（汉语文字）_百度百科",
    "url": "https://example.org/dict4",
    "source": "SearXNG/bing",
    "snippet_chars": 0,
}
PYTHON_RELEASE = {
    "title": "Python latest stable version",
    "url": "https://example.org/python",
    "source": "SearXNG/bing",
    "snippet_chars": 0,
}


def _capture(tmp_path: Path) -> Path:
    document = {
        "schema_version": "provider-routing-capture-v1",
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


def _queries(tmp_path: Path) -> Path:
    document = {
        "schema_version": "provider-routing-queries-v1",
        "cases": [CASE_X, CASE_Y],
    }
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def replay_doc(tmp_path, monkeypatch):
    queries = _queries(tmp_path)
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", queries)
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
    # The dictionary entry stays ahead of the guide: merging alone does not help.
    assert row["hit_at_3"] is False


def test_e2_ranks_with_the_assessor_not_with_the_evaluation_rule(replay_doc, tmp_path, monkeypatch):
    def assessor(results, *, canonical_query):
        # Deliberately reverse the input order: E2 must follow the assessor.
        records = [{"item": item, "assessment": {"relevance": 1.0 - index * 0.1}} for index, item in enumerate(reversed(results))]
        return records, []

    monkeypatch.setattr("src.web.source_assessment.assess_sources", assessor)
    replay_mod_replay = replay(
        capture_path=_capture(tmp_path), output=tmp_path / "replay2.json", limit=6
    )

    row = replay_mod_replay["cases"][0]["strategies"]["E2"]
    assert row["provider_calls"] == 2
    assert row["hit_at_3"] is True


def test_e3_calls_the_next_provider_only_when_the_first_is_not_good_enough(replay_doc):
    first, second = replay_doc["cases"]

    assert first["strategies"]["E3"]["triggered_extra_provider"] is True
    assert first["strategies"]["E3"]["provider_calls"] == 2
    # Y1 already has a relevant top-3 hit, so the extra provider is skipped.
    assert second["strategies"]["E3"]["triggered_extra_provider"] is False
    assert second["strategies"]["E3"]["provider_calls"] == 1
    assert replay_doc["summary"]["negative_control_skips"] == 1


def test_summary_reports_extra_calls_and_latency(replay_doc):
    summary = replay_doc["summary"]

    assert summary["cases"] == 2
    assert summary["e3_extra_provider_calls"] == 1
    for name in ("E0", "E1", "E2", "E3"):
        assert "latency_p50" in summary["strategies"][name]
        assert summary["strategies"][name]["provider_calls"] >= 2
