"""A diagnostic judge must detect controls without creating release labels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_semantic_probe import run_semantic_probe

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
BUNDLE = (ROOT / "docs/research_quality/"
          "RELEASE_BENCHMARK_ANSWER_DIAGNOSTIC_2026-09-29/answer_bundle.json")


def _inputs():
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    return json.loads(BUNDLE.read_text(encoding="utf-8")), registry, gold


def _assessment(messages, *, detect=True):
    payload = json.loads(messages[1]["content"])
    answer = payload["answer"]
    coverage, grounding, citation = "covered", "supported", "supported"
    issue_type = None
    if detect:
        if "invalid.example/unregistered" in answer:
            citation, issue_type = "gap", "wrong_citation"
        elif ("lunar gravity is the primary cause" in answer
              or "Moon does not rotate" in answer):
            grounding, issue_type = "gap", "unsupported_claim"
        elif len(answer.splitlines()) == 1:
            coverage, issue_type = "partial", "coverage_gap"
    issues = ([{"issue_type": issue_type, "reason": "Negative control detected.",
                "evidence_refs": [payload["source_id"]]}] if issue_type else [])
    return json.dumps({"question_coverage": coverage,
                       "evidence_grounding": grounding,
                       "citation_support": citation, "issues": issues})


def test_semantic_probe_detects_controls_but_never_qualifies_judge():
    bundle, registry, gold = _inputs()
    result = run_semantic_probe(
        bundle, registry, gold, ROOT, code_sha="a" * 40,
        reviewer_provider="test", reviewer_model="different-model",
        model_call=_assessment,
    )
    assert result["all_controls_detected"] is True
    assert result["formal_semantic_label"] is False
    assert result["release_observation"] is False
    assert result["release_gate"] == "NO_GO"
    assert len(result["cases"]) == 2
    assert all(len(case["assessments"]) == 4 for case in result["cases"])
    assert all(case["assessments"][0]["control_detected"] is None
               for case in result["cases"])
    assert all("wrong_citation" not in row["messages"][1]["content"]
               for case in result["cases"] for row in case["assessments"])


def test_semantic_probe_control_miss_remains_visible():
    bundle, registry, gold = _inputs()
    result = run_semantic_probe(
        bundle, registry, gold, ROOT, code_sha="a" * 40,
        reviewer_provider="test", reviewer_model="different-model",
        model_call=lambda messages: _assessment(messages, detect=False),
    )
    assert result["all_controls_detected"] is False
    assert all(case["all_controls_detected"] is False for case in result["cases"])
    assert result["formal_semantic_label"] is False


def test_semantic_probe_rejects_same_model_and_unbound_assessment():
    bundle, registry, gold = _inputs()
    with pytest.raises(ValueError, match="must differ"):
        run_semantic_probe(
            bundle, registry, gold, ROOT, code_sha="a" * 40,
            reviewer_provider="test", reviewer_model=bundle["cases"][0]["model"],
            model_call=_assessment,
        )
    with pytest.raises(ValueError, match="source-bound"):
        run_semantic_probe(
            bundle, registry, gold, ROOT, code_sha="a" * 40,
            reviewer_provider="test", reviewer_model="different-model",
            model_call=lambda messages: json.dumps({
                "question_coverage": "partial", "evidence_grounding": "gap",
                "citation_support": "gap", "issues": [{
                    "issue_type": "wrong_citation", "reason": "Wrong locator",
                    "evidence_refs": ["FORGED"],
                }],
            }),
        )
