"""Release admission and scoring fail closed on missing or stale evidence."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan, plan_digest
from src.evals.release_benchmark_registry import (
    admission_report,
    canonical_digest,
    case_content_digest,
    load_gold,
    load_registry,
    parse_gold,
    parse_registry,
)
from src.evals.release_benchmark_scoring import parse_recording, score_recordings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "release_benchmark"
PLAN = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
HEAD = "a" * 40


def _case(root: Path, *, mode: str = "frozen", modality: str = "text") -> dict:
    source_dir = root / "tests" / "fixtures" / "release_benchmark" / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / "original.txt"
    source.write_text("Original source record for a bounded pilot.\n", encoding="utf-8")
    frozen = mode == "frozen"
    case = {
        "case_id": "REL-PILOT-001", "revision": 1, "mode": mode,
        "modality": modality, "primary_focus": "retrieval",
        "question": "What does the source record state?",
        "aspects": ["main_answer"], "required_units": ["original_record"],
        "expected_conflicts": [], "limitations": [],
        "sources": [{
            "source_id": "original", "role": "primary",
            "locator": "https://example.org/original-record",
            "snapshot_path": "tests/fixtures/release_benchmark/sources/original.txt" if frozen else None,
            "sha256": sha256(source.read_bytes()).hexdigest() if frozen else None,
            "page": 1 if modality == "image" and frozen else None,
            "region": "full page" if modality == "image" and frozen else None,
        }],
        "frozen_at": "2026-09-28T00:00:00Z",
        "freshness_requirement": None if frozen else "Verify source on the run date.",
        "visual_evidence_required": modality == "image",
    }
    case["content_sha256"] = case_content_digest(case)
    return case


def _registry(root: Path, case: dict) -> tuple[dict, object]:
    raw = {"schema_version": "release-benchmark-registry-v1",
           "plan_digest": plan_digest(PLAN), "cases": [case]}
    return raw, parse_registry(raw, root, PLAN)


def _gold(registry, case: dict, *, approved: bool = True) -> tuple[dict, object]:
    review = {
        "case_id": case["case_id"], "case_content_sha256": case["content_sha256"],
        "annotator": "source-annotator", "reviewer": "independent-reviewer",
        "state": "approved" if approved else "pending",
        "source_verified": approved, "leakage_checked": approved,
        "difficulty_checked": approved, "modality_checked": approved,
        "aspect_rubric": {"main_answer": "Answer using the original record."},
        "unit_sources": {"original_record": ["original"]},
    }
    raw = {"schema_version": "release-benchmark-gold-v1",
           "registry_digest": registry.digest, "reviews": [review]}
    return raw, parse_gold(raw, registry)


def _recording(registry, gold, *, mode: str = "frozen") -> dict:
    return {
        "schema_version": "release-benchmark-observation-v1",
        "code_sha": HEAD, "plan_digest": plan_digest(PLAN),
        "registry_digest": registry.digest, "gold_digest": gold.digest,
        "mode": mode, "captured_at": "2026-09-28T00:02:00Z",
        "execution_kind": "offline_replay" if mode == "frozen" else "manual_live",
        "network_disabled": mode == "frozen",
        "configuration": {"profile": "pilot"}, "reader_flags": {"specialist": False},
        "budgets": {"reads": 2}, "model_versions": {"answer": "none"},
        "tool_versions": {"runner": "pilot-v1"},
        "time_window": {"started_at": "2026-09-28T00:00:00Z",
                        "ended_at": "2026-09-28T00:01:00Z"},
        "cases": [{
            "case_id": "REL-PILOT-001", "state": "completed", "reason": None,
            "source_reads": [{
                "source_id": "original", "locator": "https://example.org/original-record",
                "state": "read_ok", "reason": None,
                "observed_at": "2026-09-28T00:00:30Z",
                "page": None, "region": None,
                "human_reviewed_by": None if mode == "frozen" else "source-reviewer",
            }],
            "hard_failures": [],
            "metrics": {
                "required_unit_coverage": {
                    "state": "observed", "value": 1, "unit": "ratio", "reason": None,
                    "evidence_refs": ["original"], "assessor_kind": "deterministic",
                    "assessor_id": "coverage-check-v1",
                },
                "question_coverage": {
                    "state": "observed", "value": 1, "unit": "ratio", "reason": None,
                    "evidence_refs": ["original"], "assessor_kind": "manual",
                    "assessor_id": "independent-reviewer",
                },
            },
        }],
    }


def test_empty_release_registry_and_gold_remain_no_go() -> None:
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, PLAN)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    report = admission_report(PLAN, registry, gold)
    score = score_recordings(PLAN, registry, gold, ())
    assert report["admitted_release_cases"] == 0
    assert report["missing_release_cases"] == 56
    assert score["target_denominator"] == 56
    assert score["release_gate"] == "NO_GO"


def test_candidate_requires_new_namespace_and_unchanged_original_source(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    assert len(registry.cases) == 1
    original = tmp_path / case["sources"][0]["snapshot_path"]
    original.write_text("Source replaced after case freeze.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source digest mismatch"):
        _registry(tmp_path, case)
    case["case_id"] = "old_development_case"
    case["content_sha256"] = case_content_digest(case)
    with pytest.raises(ValueError, match="REL namespace"):
        _registry(tmp_path, case)


def test_frozen_source_cannot_escape_release_snapshot_directory(tmp_path) -> None:
    case = _case(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("An unrelated file.\n", encoding="utf-8")
    case["sources"][0]["snapshot_path"] = "outside.txt"
    case["sources"][0]["sha256"] = sha256(outside.read_bytes()).hexdigest()
    case["content_sha256"] = case_content_digest(case)
    with pytest.raises(ValueError, match="local release snapshot"):
        _registry(tmp_path, case)


def test_live_case_cannot_embed_snapshot_or_future_answer(tmp_path) -> None:
    case = _case(tmp_path, mode="live")
    _, registry = _registry(tmp_path, case)
    assert registry.cases[0].sources[0].snapshot_path is None
    case["sources"][0]["snapshot_path"] = "tests/fixtures/release_benchmark/sources/original.txt"
    case["content_sha256"] = case_content_digest(case)
    with pytest.raises(ValueError, match="cannot embed"):
        _registry(tmp_path, case)
    case["sources"][0]["snapshot_path"] = None
    case["future_answer"] = "unsupported content"
    case["content_sha256"] = case_content_digest(case)
    with pytest.raises(ValueError, match="fields"):
        _registry(tmp_path, case)


def test_visual_frozen_case_needs_page_region_and_gold_needs_independent_review(tmp_path) -> None:
    case = _case(tmp_path, modality="image")
    case["sources"][0]["region"] = None
    case["content_sha256"] = case_content_digest(case)
    with pytest.raises(ValueError, match="page and region"):
        _registry(tmp_path, case)
    case["sources"][0]["region"] = "full page"
    case["content_sha256"] = case_content_digest(case)
    _, registry = _registry(tmp_path, case)
    raw, gold = _gold(registry, case, approved=False)
    assert admission_report(PLAN, registry, gold)["admitted_release_cases"] == 0
    raw["reviews"][0].update(state="approved", source_verified=True,
                             leakage_checked=True, difficulty_checked=True,
                             modality_checked=True, reviewer="source-annotator")
    with pytest.raises(ValueError, match="independent"):
        parse_gold(raw, registry)


def test_gold_and_recording_bind_exact_case_and_manifest_digests(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    gold_raw, gold = _gold(registry, case)
    assert admission_report(PLAN, registry, gold)["reviewed_candidate_cases"] == 1
    assert admission_report(PLAN, registry, gold)["admitted_release_cases"] == 0
    gold_raw["reviews"][0]["case_content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="matching case revision"):
        parse_gold(gold_raw, registry)
    recording = _recording(registry, gold)
    recording["gold_digest"] = "0" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        parse_recording(recording, PLAN, registry, gold, HEAD)


def test_pilot_counts_missing_metrics_and_hard_failure_without_approval(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    _, gold = _gold(registry, case)
    positive = _recording(registry, gold)
    run = parse_recording(positive, PLAN, registry, gold, HEAD)
    report = score_recordings(PLAN, registry, gold, (run,))
    assert report["metrics"]["question_coverage"]["observed"] == 1
    assert report["metrics"]["question_coverage"]["values_by_unit"]["ratio"]["mean_observed"] == 1
    assert report["metrics"]["original_source_recall"]["values_by_unit"]["ratio"]["mean_observed"] == 1
    assert report["metrics"]["read_success"]["values_by_unit"]["ratio"]["mean_observed"] == 1
    assert report["recordings"][0]["recording_digest"] == canonical_digest(positive)
    assert len(report["recordings"][0]["configuration_digest"]) == 64
    assert report["metrics"]["evidence_grounding"]["unavailable"] == 1
    assert report["strata"]["mode"]["frozen"]["planned"] == 32
    assert report["strata"]["mode"]["live"]["reviewed_candidates"] == 0
    assert report["unadmitted_cases"] == 56
    assert report["release_gate"] == "NO_GO"
    negative = deepcopy(positive)
    negative["cases"][0]["hard_failures"] = [{
        "code": "wrong_citation", "reason": "The citation points to a different claim.",
        "evidence_refs": ["original"],
    }]
    negative["cases"][0]["metrics"]["question_coverage"]["evidence_refs"] = ["unknown"]
    with pytest.raises(ValueError, match="unknown or unread source"):
        parse_recording(negative, PLAN, registry, gold, HEAD)
    negative["cases"][0]["metrics"]["question_coverage"]["evidence_refs"] = ["original"]
    bad_report = score_recordings(
        PLAN, registry, gold, (parse_recording(negative, PLAN, registry, gold, HEAD),)
    )
    assert bad_report["hard_failures"][0]["case_id"] == "REL-PILOT-001"
    assert bad_report["hard_failures"][0]["code"] == "wrong_citation"
    assert bad_report["hard_failures"][0]["evidence_refs"] == ["original"]
    assert "hard_safety_error" in bad_report["reasons"]


def test_recording_rejects_unqualified_semantic_label_and_online_frozen_run(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    _, gold = _gold(registry, case)
    raw = _recording(registry, gold)
    raw["cases"][0]["metrics"]["question_coverage"]["assessor_kind"] = "deterministic"
    with pytest.raises(ValueError, match="external adjudication"):
        parse_recording(raw, PLAN, registry, gold, HEAD)
    raw = _recording(registry, gold)
    raw["network_disabled"] = False
    with pytest.raises(ValueError, match="offline execution"):
        parse_recording(raw, PLAN, registry, gold, HEAD)


def test_missing_recording_is_unavailable_and_never_excluded(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    _, gold = _gold(registry, case)
    score = score_recordings(PLAN, registry, gold, ())
    assert score["missing_observations"] == 1
    assert score["metrics"]["read_success"]["unavailable"] == 1
    assert score["cases"][0]["reason"] == "observation_missing"


def test_registry_digest_is_content_based_and_gold_hidden(tmp_path) -> None:
    case = _case(tmp_path)
    raw, registry = _registry(tmp_path, case)
    assert registry.digest == canonical_digest(raw)
    raw["cases"][0]["question"] = "Changed question"
    with pytest.raises(ValueError, match="content digest mismatch"):
        parse_registry(raw, tmp_path, PLAN)
    assert not any("rubric" in key for key in raw["cases"][0])


def test_registry_file_rejects_ambiguous_duplicate_json_keys(tmp_path) -> None:
    ambiguous = tmp_path / "registry.json"
    ambiguous.write_text('{"schema_version":"first","schema_version":"second"}',
                         encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate release registry JSON key"):
        load_registry(ambiguous, tmp_path, PLAN)


def test_recording_rejects_wrong_sha_and_mislabelled_cost(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    _, gold = _gold(registry, case)
    raw = _recording(registry, gold)
    with pytest.raises(ValueError, match="code SHA mismatch"):
        parse_recording(raw, PLAN, registry, gold, "b" * 40)
    raw["cases"][0]["metrics"]["attributed_cost"] = {
        "state": "observed", "value": 3.5, "unit": "ratio", "reason": None,
        "evidence_refs": [], "assessor_kind": "deterministic",
        "assessor_id": "cost-ledger-v1",
    }
    with pytest.raises(ValueError, match="value or unit mismatch"):
        parse_recording(raw, PLAN, registry, gold, HEAD)
    raw["cases"][0]["metrics"]["attributed_cost"]["unit"] = "CNY"
    report = score_recordings(
        PLAN, registry, gold, (parse_recording(raw, PLAN, registry, gold, HEAD),)
    )
    assert report["metrics"]["attributed_cost"]["values_by_unit"]["CNY"]["sum"] == 3.5


def test_live_read_requires_review_and_unread_sources_cannot_ground_semantics(tmp_path) -> None:
    case = _case(tmp_path, mode="live")
    _, registry = _registry(tmp_path, case)
    _, gold = _gold(registry, case)
    raw = _recording(registry, gold, mode="live")
    read = raw["cases"][0]["source_reads"][0]
    read["human_reviewed_by"] = None
    with pytest.raises(ValueError, match="live source reviewer"):
        parse_recording(raw, PLAN, registry, gold, HEAD)
    read["human_reviewed_by"] = "source-reviewer"
    read["state"] = "snippet_only"
    read["reason"] = "Only a search snippet was available."
    with pytest.raises(ValueError, match="unread source"):
        parse_recording(raw, PLAN, registry, gold, HEAD)
    raw["cases"][0]["metrics"] = {}
    score = score_recordings(
        PLAN, registry, gold, (parse_recording(raw, PLAN, registry, gold, HEAD),)
    )
    assert score["metrics"]["original_source_recall"]["values_by_unit"]["ratio"]["mean_observed"] == 0
    assert score["metrics"]["read_success"]["values_by_unit"]["ratio"]["mean_observed"] == 0


def test_source_read_must_match_locator_and_run_window(tmp_path) -> None:
    case = _case(tmp_path)
    _, registry = _registry(tmp_path, case)
    _, gold = _gold(registry, case)
    raw = _recording(registry, gold)
    read = raw["cases"][0]["source_reads"][0]
    read["locator"] = "https://example.org/other"
    with pytest.raises(ValueError, match="registered locator"):
        parse_recording(raw, PLAN, registry, gold, HEAD)
    read["locator"] = case["sources"][0]["locator"]
    read["observed_at"] = "2026-09-29T00:00:30Z"
    with pytest.raises(ValueError, match="outside run window"):
        parse_recording(raw, PLAN, registry, gold, HEAD)
