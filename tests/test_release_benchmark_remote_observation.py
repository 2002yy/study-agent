"""Remote inference must have its own schema and preserve v1 offline meaning."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_remote_observation import build_remote_answer_observation
from src.evals.release_benchmark_scoring import parse_recording, score_recordings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
BUNDLE = (ROOT / "docs/research_quality/"
          "RELEASE_BENCHMARK_ANSWER_DIAGNOSTIC_2026-09-29/answer_bundle.json")


def _inputs():
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    # Historical §158 capture predates the read timestamp field. The new
    # production runner must record it; this fixture exercises schema logic.
    for row in bundle["cases"]:
        row["read_observed_at"] = row["model_started_at"]
    return plan, registry, gold, bundle


def test_remote_observation_scores_two_answers_without_semantic_promotion():
    plan, registry, gold, bundle = _inputs()
    observation = build_remote_answer_observation(
        plan, registry, gold, ROOT, bundle=bundle,
        expected_code_sha=bundle["code_sha"],
    )
    recording = parse_recording(observation, plan, registry, gold, bundle["code_sha"])
    score = score_recordings(plan, registry, gold, (recording,))
    assert observation["schema_version"] == "release-benchmark-observation-v2"
    assert observation["network_disabled"] is False
    assert observation["source_network_disabled"] is True
    assert recording.inference_network == "remote_model_api"
    assert [row["case_id"] for row in observation["cases"]] == [
        "REL-F-TEXT-001", "REL-F-PDF-001",
    ]
    assert sum(row["state"] == "completed" for row in score["cases"]) == 2
    assert score["missing_observations"] == 4
    assert score["admitted_release_cases"] == 6
    assert score["schema_version"] == "release-benchmark-score-v2"
    assert score["release_gate"] == "NO_GO"
    assert score["recordings"][0]["source_network_disabled"] is True
    assert score["cases"][0]["metrics"]["question_coverage"]["state"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("network_disabled", True),
    ("source_network_disabled", False),
    ("inference_network", "offline"),
    ("execution_kind", "offline_replay"),
    ("answer_bundle_sha256", "0" * 64),
])
def test_remote_observation_rejects_false_network_or_bundle_claim(field, value):
    plan, registry, gold, bundle = _inputs()
    observation = build_remote_answer_observation(
        plan, registry, gold, ROOT, bundle=bundle,
        expected_code_sha=bundle["code_sha"],
    )
    mutated = deepcopy(observation)
    mutated[field] = value
    with pytest.raises(ValueError, match="network|bundle|offline"):
        parse_recording(mutated, plan, registry, gold, bundle["code_sha"])


def test_remote_observation_rejects_fake_semantic_label_and_missing_read_time():
    plan, registry, gold, bundle = _inputs()
    observation = build_remote_answer_observation(
        plan, registry, gold, ROOT, bundle=bundle,
        expected_code_sha=bundle["code_sha"],
    )
    mutated = deepcopy(observation)
    mutated["cases"][0]["metrics"]["question_coverage"] = {
        "state": "observed", "value": 1, "unit": "ratio", "reason": None,
        "evidence_refs": ["NOAA-SURGE"], "assessor_kind": "qualified_judge",
        "assessor_id": "self-declared",
    }
    with pytest.raises(ValueError, match="separate verified authority"):
        parse_recording(mutated, plan, registry, gold, bundle["code_sha"])
    del bundle["cases"][0]["read_observed_at"]
    with pytest.raises(ValueError, match="exact source read time"):
        build_remote_answer_observation(
            plan, registry, gold, ROOT, bundle=bundle,
            expected_code_sha=bundle["code_sha"],
        )


def test_remote_observation_rejects_stale_answer_code_and_source_drift():
    plan, registry, gold, bundle = _inputs()
    with pytest.raises(ValueError, match="current head"):
        build_remote_answer_observation(
            plan, registry, gold, ROOT, bundle=bundle,
            expected_code_sha="a" * 40,
        )
    bundle["cases"][0]["source"]["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="citation source"):
        build_remote_answer_observation(
            plan, registry, gold, ROOT, bundle=bundle,
            expected_code_sha=bundle["code_sha"],
        )
