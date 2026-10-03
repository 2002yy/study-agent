"""Target detection and issue specificity are separate semantic gates."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_semantic_calibration import calibrate_semantic_probe
from src.evals.release_benchmark_semantic_probe import run_semantic_probe

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
BUNDLE = (ROOT / "docs/research_quality/"
          "RELEASE_BENCHMARK_REMOTE_OBSERVATION_2026-09-29/answer_bundle.json")
OLD_BUNDLE = (ROOT / "docs/research_quality/"
              "RELEASE_BENCHMARK_ANSWER_DIAGNOSTIC_2026-09-29/answer_bundle.json")
OLD_PROBE = (ROOT / "docs/research_quality/"
             "RELEASE_BENCHMARK_SEMANTIC_PROBE_2026-09-29/semantic_probe.json")


def _inputs(path: Path = BUNDLE):
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    return json.loads(path.read_text(encoding="utf-8")), registry, gold


def _answer(messages, *, overflag: bool = False):
    payload = json.loads(messages[1]["content"])
    answer = payload["answer"]
    axes = {"question_coverage": "covered", "evidence_grounding": "supported",
            "citation_support": "supported"}
    issue_types = []
    if "invalid.example/unregistered" in answer:
        axes["citation_support"] = "gap"
        issue_types = ["wrong_citation"]
        if overflag:
            axes["evidence_grounding"] = "gap"
            issue_types.append("unsupported_claim")
    elif ("lunar gravity is the primary cause" in answer
          or "Moon does not rotate" in answer):
        axes["evidence_grounding"] = "gap"
        axes["citation_support"] = "gap"
        issue_types = ["unsupported_claim"]
    elif len(answer.splitlines()) == 1:
        axes["question_coverage"] = "partial"
        issue_types = ["coverage_gap"]
    axes["issues"] = [{"issue_type": issue_type, "reason": "Source-bound control.",
                       "evidence_refs": [payload["source_id"]]}
                      for issue_type in issue_types]
    return json.dumps(axes)


def _probe(bundle, registry, gold, *, overflag=False):
    return run_semantic_probe(
        bundle, registry, gold, ROOT, code_sha="a" * 40,
        reviewer_provider="deepseek", reviewer_model="different-model",
        model_call=lambda messages: _answer(messages, overflag=overflag),
    )


def test_specific_controls_can_pass_without_granting_judge_authority():
    bundle, registry, gold = _inputs()
    probe = _probe(bundle, registry, gold)
    result = calibrate_semantic_probe(
        bundle, probe, registry, gold, ROOT, calibration_code_sha="b" * 40,
    )
    assert result["target_controls_detected"] == 6
    assert result["specific_controls_passed"] == 6
    assert result["specificity_gate"] == "pass"
    assert result["same_provider_family"] is True
    assert result["qualified_judge"] is False
    assert result["formal_semantic_label"] is False
    assert result["release_observation"] is False
    assert result["release_gate"] == "NO_GO"


def test_target_detection_without_specificity_fails_calibration():
    bundle, registry, gold = _inputs()
    probe = _probe(bundle, registry, gold, overflag=True)
    result = calibrate_semantic_probe(
        bundle, probe, registry, gold, ROOT, calibration_code_sha="b" * 40,
    )
    assert result["target_controls_detected"] == 6
    assert result["specific_controls_passed"] == 4
    assert result["specificity_gate"] == "fail"


@pytest.mark.parametrize("mutation", ["parsed", "prompt", "authority", "time"])
def test_replay_rejects_tampered_probe(mutation):
    bundle, registry, gold = _inputs()
    probe = deepcopy(_probe(bundle, registry, gold))
    if mutation == "parsed":
        probe["cases"][0]["assessments"][0]["assessment"]["question_coverage"] = "partial"
    elif mutation == "prompt":
        probe["cases"][0]["assessments"][0]["messages"][1]["content"] = "{}"
    elif mutation == "time":
        probe["started_at"] = "2000-01-01T00:00:00Z"
        probe["ended_at"] = "2000-01-01T00:00:01Z"
    else:
        probe["qualified_judge"] = True
    with pytest.raises(ValueError, match="differ|prompt|precedes"):
        calibrate_semantic_probe(
            bundle, probe, registry, gold, ROOT, calibration_code_sha="b" * 40,
        )


def test_saved_real_probe_remains_diagnostic_and_fails_specificity():
    bundle, registry, gold = _inputs(OLD_BUNDLE)
    probe = json.loads(OLD_PROBE.read_text(encoding="utf-8"))
    result = calibrate_semantic_probe(
        bundle, probe, registry, gold, ROOT, calibration_code_sha="b" * 40,
    )
    assert result["target_controls_detected"] == 6
    assert result["specific_controls_passed"] < 6
    assert result["specificity_gate"] == "fail"
