"""§44C Brave qualification harness: parsing, evaluation and the frozen gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.run_brave_qualification import (
    HARD_GATE_CASES,
    build_params,
    evaluate_gate,
    evaluate_probe,
    parse_brave_payload,
    run_qualification,
)
from tools.run_recall_target_audit import TARGETS

DOCKER = next(t for t in TARGETS if t.case_id == HARD_GATE_CASES[0])
POSTGRES = next(t for t in TARGETS if t.case_id == HARD_GATE_CASES[1])
NODE = next(t for t in TARGETS if "node" in t.case_id)


def test_params_include_locale_only_in_the_variant() -> None:
    default = build_params("q", locale=False)
    localized = build_params("q", locale=True)
    assert default == {"q": "q", "count": "20"}
    assert localized["country"] == "us"
    assert localized["search_lang"] == "en"
    assert localized["ui_lang"] == "en"


def test_parser_reads_the_brave_envelope() -> None:
    payload = {
        "web": {
            "results": [
                {"url": "https://docs.docker.com/docker-hub/usage/pulls/", "title": "x"},
                {"title": "no url"},
            ]
        }
    }
    rows = parse_brave_payload(payload)
    assert [row["url"] for row in rows] == [DOCKER.url]
    assert parse_brave_payload(None) == []
    assert parse_brave_payload({}) == []


def test_probe_evaluation_reports_rank_and_deep_pages() -> None:
    rows = [
        {"url": "https://www.docker.com/", "title": "Docker", "snippet": ""},
        {"url": DOCKER.url, "title": "Pull usage and limits", "snippet": ""},
    ]
    outcome = evaluate_probe(rows, DOCKER)
    assert outcome["target_returned"] is True
    assert outcome["target_raw_rank"] == 2
    assert outcome["official_domain_hit"] is True
    assert outcome["official_deep_page_count"] == 1


def test_gate_requires_hard_cases_exact_title_hits() -> None:
    rows = [
        {"case_id": NODE.case_id, "query_class": "exact_title", "target_returned": True},
        {"case_id": NODE.case_id, "query_class": "entity_title", "target_returned": True},
        {"case_id": DOCKER.case_id, "query_class": "exact_title", "target_returned": True},
        {"case_id": DOCKER.case_id, "query_class": "entity_title", "target_returned": True},
        {"case_id": POSTGRES.case_id, "query_class": "exact_title", "target_returned": False},
        {"case_id": POSTGRES.case_id, "query_class": "entity_title", "target_returned": True},
    ]
    gate = evaluate_gate(rows)
    assert gate["passed"] is False
    assert gate["hard_gate_failures"] == [POSTGRES.case_id]

    rows[-2]["target_returned"] = True
    assert evaluate_gate(rows)["passed"] is True


def test_qualification_requires_an_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        run_qualification(output_path=tmp_path / "out.json", api_key="")
