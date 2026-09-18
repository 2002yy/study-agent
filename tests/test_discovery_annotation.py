"""§37A.2 annotation harness: blindness, contract, agreement, funnel rates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_discovery_annotation import (
    build_classification_tasks,
    build_presence_tasks,
    merge_passes,
    summarize_model_rates,
    validate_annotations,
)

CASE = "case-x"
DOCS = "https://docs.docker.com/docker-hub/usage/pulls/"
TUTORIAL = "https://www.runoob.com/docker/docker-tutorial.html"


def _audit(path: Path, *, read_docs: bool, relation: str = "lead") -> Path:
    payload = {
        "search_discovery": [
            {
                "case_id": CASE,
                "claim": "What pull-rate limits apply?",
                "query_count": 2,
                "queries": [{"page_intent": {"kind": "limit_policy"}}],
                "unique_candidates": [
                    {
                        "canonical_url": DOCS,
                        "url": DOCS,
                        "title": "Pull usage and limits",
                        "snippet": "rate limits for unauthenticated users",
                        "authority_class": "unknown",
                        "selected_for_read": "true" if read_docs else "false",
                        "selected_for_harvest": "unobserved",
                        "read_status": "read" if read_docs else "",
                        "final_relation": relation,
                    },
                    {
                        "canonical_url": TUTORIAL,
                        "url": TUTORIAL,
                        "title": "Docker tutorial",
                        "snippet": "learn docker",
                        "authority_class": "tutorial",
                        "selected_for_read": "false",
                        "selected_for_harvest": "unobserved",
                        "read_status": "",
                        "final_relation": "",
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _annotations(pass_label: str, classification: str, presence: str = "unobserved") -> dict:
    return {
        "reviewer_type": "opencode",
        "reviewer_model": "test-model",
        "pass": pass_label,
        "annotations": [
            {
                "case_id": CASE,
                "canonical_url": DOCS,
                "candidate_classification": classification,
                "target_fact_present_after_read": presence,
            },
            {
                "case_id": CASE,
                "canonical_url": TUTORIAL,
                "candidate_classification": "irrelevant",
                "target_fact_presence_after_read": "unobserved",
            },
        ],
    }


def test_classification_tasks_are_blind_and_deterministic(tmp_path: Path) -> None:
    audit = _audit(tmp_path / "audit.json", read_docs=True)

    first = build_classification_tasks(audit, pass_label="A")
    second = build_classification_tasks(audit, pass_label="A")

    assert first == second
    assert first["candidate_count"] == 2
    candidate = first["tasks"][0]["candidates"][0]
    assert set(candidate) == {"canonical_url", "url", "title", "snippet"}
    # Blindness: the *candidate payload* carries no downstream outcome fields.
    payload_text = json.dumps(first["tasks"])
    for forbidden in ("relation", "caveat", "selected_for_read", "authority_class", "read_status"):
        assert forbidden not in payload_text
    assert first["tasks"][0]["page_intent"] == "limit_policy"


def test_presence_tasks_only_cover_read_candidates(tmp_path: Path) -> None:
    audit = _audit(tmp_path / "audit.json", read_docs=True)

    tasks = build_presence_tasks(audit, pass_label="P", fetch=False)

    assert tasks["candidate_count"] == 1
    assert tasks["cases"][0]["read_candidates"][0]["canonical_url"] == DOCS


def test_annotations_must_declare_reviewer_and_valid_labels(tmp_path: Path) -> None:
    assert len(validate_annotations(_annotations("A", "likely_target"), expected_pass="A")) == 2

    wrong_type = _annotations("A", "likely_target")
    wrong_type["reviewer_type"] = "human"
    with pytest.raises(ValueError):
        validate_annotations(wrong_type)
    with pytest.raises(ValueError):
        validate_annotations(_annotations("A", "likely_target"), expected_pass="B")
    with pytest.raises(ValueError):
        validate_annotations(_annotations("A", "definitely_relevant"))


def test_merge_reports_exact_agreement_and_disagreements() -> None:
    identical = merge_passes(_annotations("A", "likely_target"), _annotations("B", "likely_target"))
    assert identical["classification_exact_agreement"] == 1.0
    assert identical["disagreements"] == []

    split = merge_passes(_annotations("A", "likely_target"), _annotations("B", "near_hit"))
    assert split["classification_exact_agreement"] == 0.5
    assert split["likely_target_disagreements"]


def test_rates_require_an_actually_read_likely_target(tmp_path: Path) -> None:
    audit = _audit(tmp_path / "audit.json", read_docs=False)
    merged = merge_passes(_annotations("A", "likely_target"), _annotations("B", "likely_target"))

    rates = summarize_model_rates(merged, audit)

    assert rates["model_target_fact_candidate_rate"] == 1.0
    # Returned but never read: presence stays unobserved, so no present rate.
    assert rates["model_likely_target_read_rate"] == 0.0
    assert rates["model_target_fact_present_rate"] is None
    assert rates["target_fact_harvest_rate"] == "unobserved"


def test_rates_follow_the_funnel_when_read_and_present(tmp_path: Path) -> None:
    audit = _audit(tmp_path / "audit.json", read_docs=True, relation="supports")
    merged = merge_passes(
        _annotations("A", "likely_target", presence="true"),
        _annotations("B", "likely_target", presence="true"),
    )

    rates = summarize_model_rates(merged, audit)

    assert rates["model_likely_target_read_rate"] == 1.0
    assert rates["model_target_fact_present_rate"] == 1.0
    assert rates["model_extractor_capture_rate"] == 1.0
    assert rates["reviewer_type"] == "opencode"
    assert "not human_* rates" in rates["note"]
