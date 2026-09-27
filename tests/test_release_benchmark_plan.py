"""Release plan validates targets and never promotes exposed controls to gold."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from src.evals.release_benchmark_plan import (
    load_release_benchmark_plan,
    parse_release_benchmark_plan,
    plan_digest,
    readiness_report,
)

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "tests" / "fixtures" / "release_benchmark" / "plan_v1.json"


def test_plan_freezes_56_slots_across_both_modes_and_all_modalities() -> None:
    plan = load_release_benchmark_plan(PLAN)
    assert plan.target_total == 56
    assert sum(cell.count for cell in plan.cells if cell.mode == "frozen") == 32
    assert sum(cell.count for cell in plan.cells if cell.mode == "live") == 24
    assert len(plan.cells) == 10
    assert sum(count for _, count in plan.focus_targets) == 56
    assert parse_release_benchmark_plan(plan.to_dict()) == plan
    assert len(plan_digest(plan)) == 64


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.update(schema_version="unknown"),
    lambda raw: raw.update(target_total=49),
    lambda raw: raw.update(target_total=True),
    lambda raw: raw["cells"].pop(),
    lambda raw: raw["cells"].__setitem__(-1, raw["cells"][0]),
    lambda raw: raw["cells"][0].update(count=True),
    lambda raw: raw["cells"][0].update(count=99),
    lambda raw: raw["focus_targets"].update(retrieval=99),
    lambda raw: raw["focus_targets"].update(new_focus=1),
])
def test_plan_rejects_schema_and_target_drift(mutation) -> None:
    raw = json.loads(PLAN.read_text(encoding="utf-8"))
    mutation(raw)
    with pytest.raises(ValueError):
        parse_release_benchmark_plan(raw)


def test_inventory_excludes_old_cases_and_reports_no_release_readiness() -> None:
    plan = load_release_benchmark_plan(PLAN)
    report = readiness_report(plan, ROOT)
    assert report["excluded_existing_cases"] == 38
    assert [(item["role"], item["count"]) for item in report["assets"]] == [
        ("development_control", 10),
        ("development_control", 10),
        ("reserved_rq1c_holdout", 12),
        ("qualification_control", 6),
    ]
    assert all(len(item["sha256"]) == 64 for item in report["assets"])
    assert report["admitted_release_cases"] == 0
    assert report["missing_release_cases"] == 56
    assert report["release_gate"] == "NO_GO"


def test_inventory_fails_closed_if_reserved_holdout_overlaps_calibration(tmp_path) -> None:
    fixture_dir = tmp_path / "tests" / "fixtures" / "research_quality"
    fixture_dir.mkdir(parents=True)
    for name in (
        "frozen_trap_cases.json", "live_trap_cases.json",
        "rq1c_bounded_holdout_manifest.json",
    ):
        shutil.copyfile(ROOT / "tests" / "fixtures" / "research_quality" / name, fixture_dir / name)
    tool_dir = tmp_path / "tools"
    tool_dir.mkdir()
    shutil.copyfile(ROOT / "tools" / "run_multimodal_qualification.py", tool_dir / "run_multimodal_qualification.py")
    holdout_path = fixture_dir / "rq1c_bounded_holdout_manifest.json"
    holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    exposed = json.loads((fixture_dir / "frozen_trap_cases.json").read_text(encoding="utf-8"))
    holdout["cases"][0]["id"] = exposed["cases"][0]["id"]
    holdout_path.write_text(json.dumps(holdout), encoding="utf-8")
    with pytest.raises(ValueError, match="overlaps"):
        readiness_report(load_release_benchmark_plan(PLAN), tmp_path)
