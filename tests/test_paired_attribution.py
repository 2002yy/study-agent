"""Deterministic tests for the paired performance attribution harness.

No network, no provider calls, no git worktrees: the orchestration is exercised
only through its pure helpers plus the fail-closed ref guard.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.run_paired_attribution import (
    CALIBRATION_CASES,
    HarnessError,
    compare_external_baseline,
    load_manifest,
    project_case_artifact,
    run_paired_attribution,
    select_calibration_cases,
    summarize_case_deltas,
    summarize_reserve_calibration,
    write_case_manifest,
)

MANIFEST = Path("tests/fixtures/research_quality/rq1c_bounded_holdout_manifest.json")


def _fingerprint(
    *,
    planner: float = 1000.0,
    assessor: float = 1000.0,
    extractor: float = 1000.0,
    bing: float = 300.0,
    bing_status: str = "ok:results_found",
    ddg: float = 6000.0,
    ddg_status: str = "failed:wallclock_timeout",
    searxng: float = 4000.0,
    searxng_status: str = "failed:url_error",
    reader: float = 500.0,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "rq1c-environment-fingerprint-v1",
        "fingerprint_id": "synthetic",
        "errors": list(errors or []),
        "deepseek": {
            "planner": {"elapsed_ms": planner},
            "assessor": {"elapsed_ms": assessor},
            "extractor": {"elapsed_ms": extractor},
        },
        "providers": {
            "providers": {
                "bing_rss": {"elapsed_ms": bing, "status": bing_status.split(":")[0], "reason": bing_status.split(":")[1]},
                "duckduckgo_html": {"elapsed_ms": ddg, "status": ddg_status.split(":")[0], "reason": ddg_status.split(":")[1]},
                "searxng": {"elapsed_ms": searxng, "status": searxng_status.split(":")[0], "reason": searxng_status.split(":")[1]},
            }
        },
        "reader": {"elapsed_ms": reader},
    }


def _case(
    case_id: str,
    *,
    elapsed: float,
    research: float,
    phases: dict[str, float] | None = None,
    reads: int = 2,
    model_calls: int = 7,
    clusters: int = 2,
    status: str = "partial",
    breakdown: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "category": "synthetic",
        "elapsed_seconds": elapsed,
        "run": {"status": status, "stop_reason": "evidence_saturated"},
        "gate": {"status": "block"},
        "finalization_breakdown": breakdown
        if breakdown is not None
        else {
            "research_seconds": research,
            "post_research_projection_seconds": 0.2,
            "answer_stage_seconds": round(elapsed - research - 0.2, 3),
            "answer_generation_seconds": round((elapsed - research) * 0.6, 3),
            "answer_claim_binding_seconds": round((elapsed - research) * 0.3, 3),
            "other_seconds": 0.0,
            "answer_stage_call_count": 2,
            "artifact_write_seconds": 0.05,
        },
        "budget_observed": {
            "read_count": reads,
            "read_attempt_count": reads,
            "model_call_count": model_calls,
            "research_model_call_count": max(0, model_calls - 1),
            "answer_generation_model_call_count": 1,
            "answer_binding_model_call_count": 0,
        },
        "search": {"attempt_count": 3},
        "metrics": {
            "cluster_count": clusters,
            "candidate_count": 5,
            "research_window": {"research_elapsed_seconds": research},
            "phase_seconds": {
                name: {"seconds": value, "calls": 1}
                for name, value in (phases or {"search": 4.0, "read": 2.0}).items()
            },
            "lead_discovery": {"no_lead_candidate": 3},
        },
    }


def test_case_selection_is_bound_to_the_holdout_manifest() -> None:
    manifest = load_manifest(MANIFEST)

    selected = select_calibration_cases(manifest)

    assert [row["label"] for row in selected] == ["C1", "C2", "C3", "C4"]
    assert [row["shape"] for row in selected] == [
        "direct-primary",
        "candidate-lead",
        "evidence-lead",
        "deadline-stress",
    ]
    assert len({row["case_id"] for row in selected}) == 4


def test_case_selection_fails_closed_on_unknown_input() -> None:
    manifest = load_manifest(MANIFEST)

    with pytest.raises(ValueError):
        select_calibration_cases(manifest, ["C1", "C9"])

    tampered = {"cases": [{"id": "rq1c-numeric-uk-inflation"}]}
    with pytest.raises(ValueError):
        select_calibration_cases(tampered)


def test_case_manifest_restricts_to_calibration_cases(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST)
    case_ids = [row["case_id"] for row in select_calibration_cases(manifest)]

    path = write_case_manifest(manifest, case_ids, tmp_path / "calibration.json")

    derived = load_manifest(path)
    assert {case["id"] for case in derived["cases"]} == set(case_ids)
    assert len(derived["cases"]) == len(case_ids)
    assert derived["schema_version"] == manifest["schema_version"]


def test_case_projection_splits_research_and_finalization() -> None:
    projection = project_case_artifact(
        _case(
            "case-x",
            elapsed=52.5,
            research=48.25,
            phases={"search": 4.5, "assessment": 1.5, "read": 3.25},
            reads=2,
            model_calls=6,
            clusters=1,
        )
    )

    assert projection["elapsed_seconds"] == 52.5
    assert projection["research_elapsed_seconds"] == 48.25
    assert projection["finalization_seconds"] == 4.25
    assert projection["phase_seconds"] == {
        "search": 4.5,
        "assessment": 1.5,
        "read": 3.25,
    }
    assert projection["reads"] == 2
    assert projection["model_calls"] == 6
    assert projection["support_clusters"] == 1
    assert projection["stop_reason"] == "evidence_saturated"


def test_case_projection_surfaces_answer_stage_truth() -> None:
    """A timed-out generation must be visible as an unavailable answer."""

    case = _case("case-z", elapsed=56.0, research=26.0)
    case["answer"] = {
        "status": "unavailable",
        "reason": "production_chat_failed",
        "text": "",
        "validation": {},
    }
    case["runner_error_type"] = "RuntimeError"

    projection = project_case_artifact(case)

    assert projection["answer_status"] == "unavailable"
    assert projection["answer_reason"] == "production_chat_failed"
    assert projection["answer_text_chars"] == 0
    assert projection["runner_error_type"] == "RuntimeError"
    assert projection["binding_outcome"] is None


def test_case_projection_reports_binding_rejection_without_calls() -> None:
    case = _case("case-w", elapsed=34.0, research=23.0)
    case["answer"] = {
        "status": "available",
        "reason": "",
        "text": "conditional answer",
        "validation": {
            "phases": {
                "answer_generation": {"outcome": "completed", "model_calls": 1},
                "answer_claim_binding": {
                    "outcome": "rejected",
                    "error_type": "missing_evidence_brief",
                    "model_calls": 0,
                },
            }
        },
    }

    projection = project_case_artifact(case)

    assert projection["answer_status"] == "available"
    assert projection["binding_outcome"] == "rejected"
    assert projection["binding_error_type"] == "missing_evidence_brief"


def test_case_projection_tolerates_missing_phase_telemetry() -> None:
    case = _case("case-y", elapsed=50.0, research=46.0)
    case["metrics"]["phase_seconds"] = None
    case["metrics"]["research_window"] = None

    projection = project_case_artifact(case)

    assert projection["phase_seconds"] == {}
    assert projection["research_elapsed_seconds"] is None
    assert projection["finalization_seconds"] is None


def test_external_baseline_within_tolerance_is_stable() -> None:
    first = _fingerprint()
    second = _fingerprint(planner=1400.0, bing=500.0, searxng=4600.0)

    result = compare_external_baseline(first, second)

    assert result["status"] == "stable"
    assert result["attribution_allowed"] is True
    assert result["drifts"] == []
    assert result["material_provider_changes"] == []


def test_external_baseline_drift_blocks_attribution() -> None:
    first = _fingerprint()
    second = _fingerprint(assessor=4200.0, reader=3000.0)

    result = compare_external_baseline(first, second)

    assert result["status"] == "environment_unstable"
    assert result["attribution_allowed"] is False
    drifted = {item["metric"] for item in result["drifts"]}
    assert drifted == {"deepseek.assessor", "reader"}


def test_external_baseline_provider_state_change_is_material() -> None:
    first = _fingerprint()
    second = _fingerprint(bing_status="failed:not_configured")

    result = compare_external_baseline(first, second)

    assert result["status"] == "environment_unstable"
    assert result["material_provider_changes"] == [
        {
            "provider": "bing_rss",
            "first": "ok:results_found",
            "second": "failed:not_configured",
        }
    ]


def test_external_baseline_missing_metric_or_probe_error_is_unstable() -> None:
    first = _fingerprint()
    second = _fingerprint()
    second["providers"]["providers"].pop("searxng")

    assert compare_external_baseline(first, second)["status"] == "environment_unstable"

    assert (
        compare_external_baseline(first, _fingerprint(errors=["probe failed"]))["status"]
        == "environment_unstable"
    )


def test_case_deltas_keep_raw_values_and_use_baseline_mean() -> None:
    baseline_runs = [
        {"cases": [project_case_artifact(_case("case-x", elapsed=50.0, research=46.0, clusters=1))]},
        {"cases": [project_case_artifact(_case("case-x", elapsed=54.0, research=50.0, clusters=1))]},
    ]
    candidate_run = {
        "cases": [
            project_case_artifact(_case("case-x", elapsed=52.0, research=48.0, clusters=2))
        ]
    }

    rows = summarize_case_deltas(baseline_runs, candidate_run)

    assert len(rows) == 1
    row = rows[0]
    elapsed = row["metrics"]["elapsed_seconds"]
    assert elapsed["baseline"]["samples"] == [50.0, 54.0]
    assert elapsed["baseline"]["count"] == 2
    assert elapsed["baseline"]["p50"] == 54.0
    assert elapsed["candidate"]["p50"] == 52.0
    assert elapsed["delta_p50"] == -2.0
    assert elapsed["direction"] == "lower_is_better"
    assert row["metrics"]["support_clusters"]["delta_p50"] == 1.0
    assert row["metrics"]["support_clusters"]["direction"] == "higher_is_better"
    assert row["phases"]["search"]["baseline"]["samples"] == [4.0, 4.0]


def test_case_deltas_report_finalization_breakdown_distributions() -> None:
    baseline_runs = [
        {
            "cases": [
                project_case_artifact(_case("case-x", elapsed=50.0, research=20.0))
            ]
        }
    ]
    candidate_run = {
        "cases": [
            project_case_artifact(_case("case-x", elapsed=60.0, research=22.0))
        ]
    }

    rows = summarize_case_deltas(baseline_runs, candidate_run)

    metrics = rows[0]["metrics"]
    assert metrics["answer_generation_seconds"]["baseline"]["p50"] == 18.0
    assert metrics["answer_binding_seconds"]["candidate"]["p50"] == 11.4
    assert metrics["answer_stage_seconds"]["candidate"]["p50"] == 37.8
    assert metrics["artifact_write_seconds"]["candidate"]["p50"] == 0.05


def test_load_case_artifacts_reads_repeat_files(tmp_path: Path) -> None:
    from tools.run_paired_attribution import _load_case_artifacts

    for repeat, elapsed in ((1, 50.0), (2, 52.0), (3, 48.0)):
        artifact = {
            "schema_version": "rq1c-calibration-run-v1",
            "cases": [_case("case-x", elapsed=elapsed, research=20.0)],
        }
        (tmp_path / f"case-x__r{repeat}.json").write_text(
            json.dumps(artifact), encoding="utf-8"
        )

    loaded = _load_case_artifacts(tmp_path, ["case-x"], 3)

    assert loaded["missing_cases"] == []
    assert [item["elapsed_seconds"] for item in loaded["cases"]] == [50.0, 52.0, 48.0]


def test_reserve_calibration_reports_percentiles_and_adequacy() -> None:
    runs = [
        {
            "cases": [
                project_case_artifact(_case(f"case-{index}", elapsed=50.0 + index, research=45.0))
                for index in range(4)
            ]
        }
    ]

    result = summarize_reserve_calibration(runs)

    assert result["sample_count"] == 4
    # Finalization samples are 5, 6, 7, 8 seconds (nearest-rank percentiles).
    assert result["finalization_p50_seconds"] == 7.0
    assert result["finalization_p90_seconds"] == 8.0
    assert result["finalization_max_seconds"] == 8.0
    assert result["sample_adequate_for_reserve"] is False
    distributions = result["distributions"]
    assert distributions["research"]["p50"] == 45.0
    assert distributions["answer_generation"]["count"] == 4
    assert distributions["answer_binding"]["samples"]


def test_reserve_calibration_includes_answer_stage_split() -> None:
    runs = [
        {
            "cases": [
                project_case_artifact(_case("case-x", elapsed=55.0, research=25.0))
            ]
        }
    ]

    result = summarize_reserve_calibration(runs)

    distributions = result["distributions"]
    assert distributions["answer_generation"]["p50"] == 18.0
    assert distributions["answer_binding"]["p50"] == 9.0
    assert distributions["answer_stage"]["p50"] == 29.8
    assert distributions["artifact_write"]["p50"] == 0.05


def test_paired_run_requires_distinct_refs(tmp_path: Path) -> None:
    with pytest.raises(HarnessError):
        run_paired_attribution(
            repo=Path.cwd(),
            baseline_ref="HEAD",
            candidate_ref="HEAD",
            labels=["C1"],
            output=tmp_path / "out.json",
            workdir=tmp_path / "work",
        )


def test_calibration_case_ids_exist_in_the_holdout_manifest() -> None:
    manifest = load_manifest(MANIFEST)
    case_ids = {case["id"] for case in manifest["cases"]}

    for row in CALIBRATION_CASES:
        assert row["case_id"] in case_ids, row
        assert row["rationale"]


def test_calibration_runner_selects_a_subset_without_touching_the_guard() -> None:
    from tools.run_rq1c_calibration import DEFAULT_CASES, _load_cases

    manifest = load_manifest(MANIFEST)
    default_ids = {case["id"] for case in manifest["cases"]}
    assert set(DEFAULT_CASES) <= default_ids

    selected = _load_cases(MANIFEST, ["rq1c-provenance-xz"])

    assert [case["id"] for case in selected] == ["rq1c-provenance-xz"]
    assert selected[0]["question"]
    # The strict qualification entrypoint keeps its own 12-case guard.
    from tools.run_rq1c_bounded_qualification_core import _load_manifest

    assert len(_load_manifest(MANIFEST)) == 12


def test_calibration_runner_fails_closed_on_unknown_case_id() -> None:
    from tools.run_rq1c_calibration import _load_cases

    with pytest.raises(ValueError):
        _load_cases(MANIFEST, ["rq1c-does-not-exist"])
