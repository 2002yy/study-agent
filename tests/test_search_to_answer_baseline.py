"""Contracts for the Search-to-Answer retrieval baseline harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_search_to_answer_baseline import (
    PROVIDER_MODES,
    load_cases,
    run_baseline,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "search_to_answer" / "baseline_v1.json"


def _fixture_document() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_frozen_case_set_covers_the_four_task_categories():
    document = _fixture_document()
    cases = document["cases"]

    assert document["schema_version"] == "search-to-answer-baseline-v1"
    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20

    categories = [case["category"] for case in cases]
    for category in ("realtime", "comparison", "deep_research", "follow_up"):
        assert categories.count(category) == 5

    round_one = {case["id"] for case in cases if case.get("round_1")}
    assert round_one == {"A01", "B01", "B02", "C01", "D01"}


def test_every_case_declares_input_expectation_and_evaluation():
    for case in _fixture_document()["cases"]:
        assert case["prompt"].strip()
        assert case["expected_behavior"].strip()
        assert case["evaluation"]["method"] in {"game_manual_5d", "non_game_manual_5d"}
        assert case["evaluation"]["checks"]
        assert case["external_conditions"]["network"] == "public web"


def test_follow_up_cases_carry_their_second_turn():
    follow_ups = [
        case for case in _fixture_document()["cases"] if case["category"] == "follow_up"
    ]

    assert follow_ups
    for case in follow_ups:
        assert case["follow_up"].strip()


def test_load_cases_rejects_unknown_selection():
    with pytest.raises(ValueError):
        load_cases(FIXTURE, {"NOPE"})


def test_provider_modes_are_isolated_and_restored(tmp_path, monkeypatch):
    """Each mode sets its own switches and the process environment is restored."""

    seen: list[dict[str, str]] = []

    monkeypatch.setenv("WEB_ENABLE_SEARXNG", "keep-me")
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "keep-me")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "keep-me")

    def fake_search(self, query, *, max_results=5, now=None):  # noqa: ANN001
        import os

        seen.append(
            {
                "searxng": os.environ.get("WEB_ENABLE_SEARXNG", ""),
                "bing": os.environ.get("WEB_ENABLE_BING_RSS", ""),
                "ddg": os.environ.get("WEB_ENABLE_DUCKDUCKGO", ""),
            }
        )
        return {
            "status": "ok",
            "reason": "results_found",
            "attempted_queries": [query],
            "results": [
                {
                    "title": "t",
                    "url": "https://example.org/",
                    "snippet": "",
                    "source": "DuckDuckGo",
                }
            ],
            "provider_errors": [],
        }

    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.search_detailed",
        fake_search,
    )
    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.read",
        lambda self, url, **kwargs: {"ok": False, "url": url, "error_code": "http_403"},
    )

    output = tmp_path / "artifact.json"
    artifact = run_baseline(
        cases_path=FIXTURE,
        output_path=output,
        modes=["auto", "ddg_only"],
        max_results=1,
        max_reads=1,
        max_chars=500,
        selected_cases={"A01", "D01"},
    )

    assert len(artifact["records"]) == 4
    assert seen[0] == {"searxng": "keep-me", "bing": "keep-me", "ddg": "keep-me"}
    assert seen[2] == {"searxng": "false", "bing": "false", "ddg": "true"}
    assert fixed_mode("ddg_only")["WEB_ENABLE_BING_RSS"] == "false"

    # Each mode is scoped to the run: the caller's environment comes back.
    import os

    assert os.environ.get("WEB_ENABLE_SEARXNG") == "keep-me"
    assert output.exists()
    assert artifact["scope"]["uses_model_synthesis"] is False
    assert artifact["not_measured"]["ttfu_seconds"]


def test_auto_after_another_mode_still_means_auto(tmp_path, monkeypatch):
    """`auto` must be the deployment configuration, not the previous mode's leavings."""

    seen: list[dict[str, str]] = []

    monkeypatch.setenv("WEB_ENABLE_SEARXNG", "true")
    monkeypatch.setenv("WEB_ENABLE_BING_RSS", "true")
    monkeypatch.setenv("WEB_ENABLE_DUCKDUCKGO", "true")

    def fake_search(self, query, *, max_results=5, now=None):  # noqa: ANN001
        import os

        seen.append(
            {
                "searxng": os.environ.get("WEB_ENABLE_SEARXNG", ""),
                "bing": os.environ.get("WEB_ENABLE_BING_RSS", ""),
                "ddg": os.environ.get("WEB_ENABLE_DUCKDUCKGO", ""),
            }
        )
        return {
            "status": "ok",
            "reason": "results_found",
            "attempted_queries": [query],
            "results": [],
            "provider_errors": [],
        }

    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.search_detailed",
        fake_search,
    )

    run_baseline(
        cases_path=FIXTURE,
        output_path=tmp_path / "artifact.json",
        modes=["ddg_only", "auto"],
        max_results=1,
        max_reads=0,
        max_chars=500,
        selected_cases={"A01"},
    )

    assert seen[0] == {"searxng": "false", "bing": "false", "ddg": "true"}
    assert seen[1] == {"searxng": "true", "bing": "true", "ddg": "true"}


def fixed_mode(name: str) -> dict[str, str]:
    return PROVIDER_MODES[name]


def test_summary_reports_snippets_and_reads(tmp_path, monkeypatch):
    def fake_search(self, query, *, max_results=5, now=None):  # noqa: ANN001
        return {
            "status": "ok",
            "reason": "results_found",
            "attempted_queries": [query],
            "results": [
                {
                    "title": "with snippet",
                    "url": "https://example.org/a",
                    "snippet": "text",
                    "source": "Bing RSS",
                },
                {
                    "title": "without snippet",
                    "url": "https://example.org/b",
                    "snippet": "",
                    "source": "DuckDuckGo",
                },
            ],
            "provider_errors": [],
        }

    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.search_detailed",
        fake_search,
    )
    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.read",
        lambda self, url, **kwargs: {"ok": True, "url": url, "content": "body"},
    )

    artifact = run_baseline(
        cases_path=FIXTURE,
        output_path=tmp_path / "artifact.json",
        modes=["auto"],
        max_results=2,
        max_reads=2,
        max_chars=500,
        selected_cases={"A01"},
    )

    summary = artifact["summary"]["auto"]
    assert summary["result_sources"] == {"Bing RSS": 1, "DuckDuckGo": 1}
    assert summary["snippet_present_ratio"] == 0.5
    # "body" is a technical success but far too short to be usable evidence.
    assert summary["top_k_url_technical_read_successes"] == 2
    assert summary["top_k_url_evidence_usable_reads"] == 0


def test_read_sampling_is_recorded_and_not_called_relevance_quality(tmp_path, monkeypatch):
    def fake_search(self, query, *, max_results=5, now=None):  # noqa: ANN001
        return {
            "status": "ok",
            "reason": "results_found",
            "attempted_queries": [query],
            "results": [
                {"title": "a", "url": "https://example.org/a", "snippet": "", "source": "Bing RSS"},
                {"title": "b", "url": "https://example.org/b", "snippet": "", "source": "Bing RSS"},
                {"title": "c", "url": "https://example.org/c", "snippet": "", "source": "Bing RSS"},
            ],
            "provider_errors": [],
        }

    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.search_detailed",
        fake_search,
    )
    monkeypatch.setattr(
        "tools.run_search_to_answer_baseline.GeneralWebGateway.read",
        lambda self, url, **kwargs: {"ok": True, "url": url, "content": "x" * 900},
    )

    artifact = run_baseline(
        cases_path=FIXTURE,
        output_path=tmp_path / "artifact.json",
        modes=["auto"],
        max_results=3,
        max_reads=1,
        max_chars=2000,
        selected_cases={"A01"},
        min_evidence_chars=800,
    )

    record = artifact["records"][0]
    assert record["read_sampling"] == {
        "rule": "results[:max_reads]",
        "max_reads": 1,
        "sampled": 1,
        "available_results": 3,
    }
    assert record["top_k_url_technical_read_successes"] == 1
    assert record["top_k_url_evidence_usable_reads"] == 1
    contract = artifact["read_contract"]
    assert contract["related_source_read_quality"] == "not_measured"
    assert contract["min_evidence_chars"] == 800
    assert "no relevance filter" in contract["selection"]
