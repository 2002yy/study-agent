"""Strict, offline plan and asset inventory for the future release benchmark.

This module does not score cases or turn development fixtures into release gold.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Literal

from src.evals.research_quality import load_research_quality_eval_cases

PLAN_SCHEMA_VERSION = "release-benchmark-plan-v1"
READINESS_SCHEMA_VERSION = "release-benchmark-readiness-v1"
Mode = Literal["frozen", "live"]
Modality = Literal["text", "pdf", "image", "chart", "mixed"]
Focus = Literal[
    "retrieval", "unit_adequacy", "conflict", "visual_value",
    "synthesis", "auditor", "continuity",
]
MODES = ("frozen", "live")
MODALITIES = ("text", "pdf", "image", "chart", "mixed")
FOCUSES: tuple[Focus, ...] = (
    "retrieval", "unit_adequacy", "conflict", "visual_value",
    "synthesis", "auditor", "continuity",
)
_MULTIMODAL_CASE = re.compile(r'"id": "(Q[1-6]_[^"]+)"')


@dataclass(frozen=True)
class TargetCell:
    mode: Mode
    modality: Modality
    count: int

    def to_dict(self) -> dict[str, object]:
        return {"mode": self.mode, "modality": self.modality, "count": self.count}


@dataclass(frozen=True)
class ReleaseBenchmarkPlan:
    target_total: int
    cells: tuple[TargetCell, ...]
    focus_targets: tuple[tuple[Focus, int], ...]
    schema_version: str = PLAN_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_total": self.target_total,
            "cells": [cell.to_dict() for cell in self.cells],
            "focus_targets": {key: count for key, count in self.focus_targets},
        }


def load_release_benchmark_plan(path: str | Path) -> ReleaseBenchmarkPlan:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("unreadable release benchmark plan") from exc
    return parse_release_benchmark_plan(raw)


def parse_release_benchmark_plan(raw: Any) -> ReleaseBenchmarkPlan:
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version", "target_total", "cells", "focus_targets",
    }:
        raise ValueError("invalid release benchmark plan object")
    if raw["schema_version"] != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported release benchmark plan schema")
    total = raw["target_total"]
    if type(total) is not int or not 50 <= total <= 60:
        raise ValueError("release benchmark target must be 50 to 60")
    raw_cells = raw["cells"]
    if not isinstance(raw_cells, list) or len(raw_cells) != len(MODES) * len(MODALITIES):
        raise ValueError("release benchmark requires every mode and modality cell")
    cells: list[TargetCell] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_cells:
        if not isinstance(item, dict) or set(item) != {"mode", "modality", "count"}:
            raise ValueError("invalid release benchmark target cell")
        mode, modality, count = item["mode"], item["modality"], item["count"]
        if mode not in MODES or modality not in MODALITIES or type(count) is not int or count < 1:
            raise ValueError("invalid release benchmark target value")
        if (mode, modality) in seen:
            raise ValueError("duplicate release benchmark target cell")
        seen.add((mode, modality))
        cells.append(TargetCell(mode, modality, count))  # type: ignore[arg-type]
    if seen != {(mode, modality) for mode in MODES for modality in MODALITIES}:
        raise ValueError("missing release benchmark target cell")
    if sum(cell.count for cell in cells) != total:
        raise ValueError("release benchmark cell counts do not sum to target")
    if any(sum(cell.count for cell in cells if cell.mode == mode) < 20 for mode in MODES):
        raise ValueError("release benchmark needs at least 20 cases per mode")
    raw_focus = raw["focus_targets"]
    if not isinstance(raw_focus, dict) or set(raw_focus) != set(FOCUSES):
        raise ValueError("release benchmark focus set mismatch")
    if any(type(value) is not int or value < 1 for value in raw_focus.values()):
        raise ValueError("invalid release benchmark focus count")
    if sum(raw_focus.values()) != total:
        raise ValueError("release benchmark focus counts do not sum to target")
    return ReleaseBenchmarkPlan(
        target_total=total,
        cells=tuple(sorted(cells, key=lambda cell: (cell.mode, cell.modality))),
        focus_targets=tuple((key, raw_focus[key]) for key in FOCUSES),
    )


def plan_digest(plan: ReleaseBenchmarkPlan) -> str:
    encoded = json.dumps(
        plan.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def inspect_calibration_assets(root: Path) -> dict[str, object]:
    """Inventory existing exposed controls; none are admitted release cases."""

    fixture_dir = root / "tests" / "fixtures" / "research_quality"
    assets: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for filename, role in (
        ("frozen_trap_cases.json", "development_control"),
        ("live_trap_cases.json", "development_control"),
    ):
        path = fixture_dir / filename
        cases = load_research_quality_eval_cases(path)
        ids = {case.id for case in cases}
        if len(ids) != len(cases) or seen_ids & ids:
            raise ValueError("duplicate calibration case identity")
        seen_ids.update(ids)
        assets.append(_asset(root, path, role, len(cases)))
    holdout_path = fixture_dir / "rq1c_bounded_holdout_manifest.json"
    try:
        holdout = json.loads(holdout_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("unreadable reserved holdout") from exc
    if not isinstance(holdout, dict) or holdout.get("schema_version") != "rq1c-bounded-holdout-manifest-v1":
        raise ValueError("unsupported reserved holdout schema")
    records = holdout.get("cases")
    if not isinstance(records, list) or not records or any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not item["id"].strip()
        for item in records
    ):
        raise ValueError("invalid reserved holdout cases")
    ids = {item["id"] for item in records}
    if len(ids) != len(records) or seen_ids & ids:
        raise ValueError("reserved holdout identity overlaps calibration")
    seen_ids.update(ids)
    assets.append(_asset(root, holdout_path, "reserved_rq1c_holdout", len(records)))
    multimodal_path = root / "tools" / "run_multimodal_qualification.py"
    try:
        multimodal_ids = _MULTIMODAL_CASE.findall(multimodal_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError("unreadable multimodal qualification") from exc
    if len(multimodal_ids) != 6 or {item.split("_", 1)[0] for item in multimodal_ids} != {
        "Q1", "Q2", "Q3", "Q4", "Q5", "Q6",
    }:
        raise ValueError("multimodal qualification case inventory drift")
    multimodal_count = len(multimodal_ids)
    assets.append(_asset(root, multimodal_path, "qualification_control", multimodal_count))
    return {
        "assets": assets,
        "excluded_existing_cases": len(seen_ids) + multimodal_count,
    }


def readiness_report(plan: ReleaseBenchmarkPlan, root: Path) -> dict[str, object]:
    inventory = inspect_calibration_assets(root)
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "plan_digest": plan_digest(plan),
        "target_total": plan.target_total,
        "admitted_release_cases": 0,
        "missing_release_cases": plan.target_total,
        "release_gate": "NO_GO",
        "reason": "independent_release_case_registry_absent",
        **inventory,
    }


def _asset(root: Path, path: Path, role: str, count: int) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "count": count,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }
