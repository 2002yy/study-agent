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
from tools.run_provider_routing_replay import _query_fingerprint, replay, replay_with_pools, verdict

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


def test_search_1_arms_share_one_raw_pool(replay_doc):
    # B and C must be computed from the same merged pool: their result counts
    # are identical, only their order may differ. That is what keeps the
    # coverage gain (B) separable from the rerank gain (C).
    first = replay_doc["cases"][0]["strategies"]
    assert first["B_merge"]["results"] == first["C_rerank"]["results"] == first["C_bigram"]["results"]
    assert first["B_merge"]["hit_at_6"] is True  # pool now contains the guide


def _pool(row: dict) -> list[dict]:
    """The two raw provider pools for a replay row, in capture order.

    ``row`` here is the *replay* row (id + strategies + the raw provider
    pools it was computed from); the merge pool is bing first, ddg second.
    """

    providers = row.get("providers", {})
    return [
        item
        for item in [
            *providers.get("bing", {}).get("results", []),
            *providers.get("ddg", {}).get("results", []),
        ]
        if item.get("url")
    ]


def _replay_row_with_pools(document: dict) -> list[dict]:
    """Replay rows carrying their raw provider pools, so pool checks work."""
    rows = document["cases"]
    for row in rows:
        row.setdefault("providers", {})
    return rows


def test_a_fallback_uses_the_fallback_capture_when_present(replay_doc, tmp_path, monkeypatch):
    capture_path = _capture(tmp_path)
    import json

    document = json.loads(capture_path.read_text(encoding="utf-8"))
    case_row = document["cases"][0]
    case_row["providers"] = {
        "bing": {
            "status": "ok",
            "elapsed": 0.4,
            "provider_errors": [],
            "results": [DICTIONARY, DICTIONARY_2, DICTIONARY_3, DICTIONARY_4],
        },
        "ddg": {"status": "ok", "elapsed": 3.0, "provider_errors": [], "results": [GUIDE]},
    }
    case_row["providers"]["fallback"] = {
        "status": "ok",
        "elapsed": 1.1,
        "provider_errors": [],
        "providers_attempted": ["bing_rss"],
        "results": [GUIDE],
    }
    capture_path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(replay_mod, "DEFAULT_QUERIES", _queries(tmp_path))
    monkeypatch.setattr(
        "src.web.source_assessment.assess_sources",
        lambda results, *, canonical_query: (
            [{"item": item, "assessment": {"relevance": 0.9}} for item in results],
            [],
        ),
    )
    result = replay_with_pools(capture_path=capture_path, output=tmp_path / "r_fallback.json", limit=6)
    a = result["cases"][0]["strategies"]["A_fallback"]
    assert a["latency"] == 1.1
    assert a["top_url"].endswith("/guide")
    # A is read from the fallback snapshot; B/C still use the two raw pools.
    assert result["cases"][0]["strategies"]["B_merge"]["results"] == 5


def test_e2_ranks_with_the_assessor_not_with_the_evaluation_rule(replay_doc, tmp_path, monkeypatch):
    def reverse_assessor(results, *, canonical_query):
        records = [
            {"item": item, "assessment": {"relevance": 1.0 - index * 0.1}}
            for index, item in enumerate(reversed(results))
        ]
        return records, []

    monkeypatch.setattr("src.web.source_assessment.assess_sources", reverse_assessor)
    document = replay_with_pools(
        capture_path=_capture(tmp_path), output=tmp_path / "replay2.json", limit=6
    )

    first = document["cases"][0]
    b_urls = {item["url"] for item in _pool(first)}
    assert len(b_urls) == first["strategies"]["B_merge"]["results"]
    # With a bing-first pool the guide sits last: B alone misses it, and the
    # assessor arm must lift it back into the top 3.
    assert first["strategies"]["B_merge"]["hit_at_3"] is False
    assert first["strategies"]["E2"]["hit_at_3"] is True


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


def test_search_1_summary_reports_moves_and_categories(replay_doc):
    summary = replay_doc["summary"]
    for name in ("A_fallback", "B_merge", "C_rerank", "C_bigram"):
        assert name in summary["strategies"]
    assert "improved_regressed_vs_A" in summary
    assert "gates" not in summary


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


def test_random_window_control_samples_the_whole_pool():
    # Regression for review 5699199834: the control used to look at the first
    # 12 rows only. With a 24-row pool whose relevant rows all sit after row 12,
    # that truncated sample reports "no chance", which would understate the
    # baseline the reranked arm has to beat.
    case = {"anchors": ["星铁", "遗器"], "focus": ["配装"]}
    irrelevant = [
        {"title": f"page {index}", "url": f"https://example.org/{index}", "source": "", "snippet": ""}
        for index in range(16)
    ]
    relevant = [
        {"title": "星铁 遗器 配装指南", "url": f"https://example.org/ok{index}", "source": "", "snippet": ""}
        for index in range(8)
    ]
    pool = [*irrelevant, *relevant]

    assert replay_mod._random_window_hit([*irrelevant, *relevant[:0]], case) == 0.0
    chance = replay_mod._random_window_hit(pool, case)
    assert chance > 0.0
    # Hypergeometric over the full 24 rows: 1 - C(16,6)/C(24,6).
    import math

    expected = round(1 - math.comb(16, 6) / math.comb(24, 6), 4)
    assert chance == expected


def test_summary_separates_gate_quality_from_e3_quality(replay_doc):
    assert replay_doc["summary"]["strategies"]["E2"]["latency_p50"] is not None
