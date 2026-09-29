"""Replay and calibrate a semantic probe without granting scoring authority."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, cast

from src.evals.release_benchmark_registry import ReleaseGold, ReleaseRegistry
from src.evals.release_benchmark_semantic_probe import run_semantic_probe

SCHEMA = "release-benchmark-semantic-calibration-v1"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_AXES = ("question_coverage", "evidence_grounding", "citation_support")
_EXPECTED = {
    "wrong_citation": (("covered", "supported", "gap"), "wrong_citation",
                       {"wrong_citation"}),
    "missing_aspect": (("partial", "supported", "supported"), "coverage_gap",
                       {"coverage_gap"}),
    "unsupported_claim": (("covered", "gap", "gap"), "unsupported_claim",
                          {"unsupported_claim", "wrong_citation"}),
}
_TARGET_AXIS = {
    "wrong_citation": "citation_support",
    "missing_aspect": "question_coverage",
    "unsupported_claim": "evidence_grounding",
}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _utc_instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("semantic probe timestamp is invalid")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("semantic probe timestamp is invalid") from exc
    if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
        raise ValueError("semantic probe timestamp is not UTC")
    return instant


def _replay_probe(bundle: dict[str, object], probe: dict[str, object],
                  registry: ReleaseRegistry, gold: ReleaseGold, root: Path) -> None:
    """Rebuild every prompt and parsed judgment from the saved raw responses."""
    try:
        saved_cases = cast(list[dict[str, Any]], probe["cases"])
        saved = [assessment for case in saved_cases
                 for assessment in case["assessments"]]
        review_code_sha = cast(str, probe["review_code_sha"])
        reviewer_provider = cast(str, probe["reviewer_provider"])
        reviewer_model = cast(str, probe["reviewer_model"])
    except (KeyError, TypeError) as exc:
        raise ValueError("semantic probe artifact shape is invalid") from exc
    cursor = 0

    def replay(messages: list[dict[str, str]]) -> str:
        nonlocal cursor
        if cursor >= len(saved) or saved[cursor]["messages"] != messages:
            raise ValueError("semantic probe prompt differs from frozen source")
        raw = saved[cursor]["raw_model_response"]
        cursor += 1
        return cast(str, raw)

    rebuilt = run_semantic_probe(
        bundle, registry, gold, root, code_sha=review_code_sha,
        reviewer_provider=reviewer_provider, reviewer_model=reviewer_model,
        model_call=replay,
    )
    if cursor != len(saved):
        raise ValueError("semantic probe has extra assessments")
    start = _utc_instant(probe.get("started_at"))
    end = _utc_instant(probe.get("ended_at"))
    if end < start:
        raise ValueError("semantic probe time window is reversed")
    answer_rows = cast(list[dict[str, Any]], bundle["cases"])
    if start < max(_utc_instant(row["model_ended_at"]) for row in answer_rows):
        raise ValueError("semantic probe precedes captured answers")
    rebuilt["started_at"] = probe["started_at"]
    rebuilt["ended_at"] = probe["ended_at"]
    if rebuilt != probe:
        raise ValueError("semantic probe fields differ from raw-response replay")


def calibrate_semantic_probe(
    bundle: dict[str, object], probe: dict[str, object],
    registry: ReleaseRegistry, gold: ReleaseGold, root: Path, *,
    calibration_code_sha: str,
) -> dict[str, object]:
    """Check target detection and specificity; remain diagnostic in all cases."""
    if not _SHA.fullmatch(calibration_code_sha):
        raise ValueError("calibration needs an exact code SHA")
    _replay_probe(bundle, probe, registry, gold, root)
    cases = []
    for saved_case in cast(list[dict[str, Any]], probe["cases"]):
        assessments = saved_case["assessments"]
        actual = assessments[0]
        actual_judgment = actual["assessment"]
        actual_clean = (actual["dimension_consistent"] is True
                        and tuple(actual_judgment[axis] for axis in _AXES)
                        == ("covered", "supported", "supported")
                        and actual_judgment["issues"] == [])
        controls = []
        for row in assessments[1:]:
            variant = row["variant"]
            axes, required_issue, allowed_issues = _EXPECTED[variant]
            judgment = row["assessment"]
            counts = Counter(issue["issue_type"] for issue in judgment["issues"])
            observed_axes = tuple(judgment[axis] for axis in _AXES)
            target_index = _AXES.index(_TARGET_AXIS[variant])
            target_detected = (row["dimension_consistent"] is True
                               and observed_axes[target_index] == axes[target_index]
                               and counts[required_issue] >= 1)
            specific = (target_detected and observed_axes == axes
                        and counts[required_issue] == 1
                        and set(counts) <= allowed_issues
                        and all(count == 1 for count in counts.values()))
            controls.append({
                "variant": variant, "target_detected": target_detected,
                "specific": specific,
                "expected_axes": dict(zip(_AXES, axes, strict=True)),
                "observed_axes": dict(zip(_AXES, observed_axes, strict=True)),
                "issue_types": dict(sorted(counts.items())),
            })
        cases.append({"case_id": saved_case["case_id"],
                      "answer_sha256": saved_case["answer_sha256"],
                      "actual_clean_diagnostic": actual_clean,
                      "controls": controls})
    controls = [row for case in cases for row in case["controls"]]
    answer_providers = {cast(str, row["provider"])
                        for row in cast(list[dict[str, Any]], bundle["cases"])}
    specificity_pass = (all(case["actual_clean_diagnostic"] for case in cases)
                        and all(row["specific"] for row in controls))
    return {
        "schema_version": SCHEMA,
        "calibration_code_sha": calibration_code_sha,
        "answer_bundle_sha256": probe["answer_bundle_sha256"],
        "probe_sha256": sha256(_json_bytes(probe)).hexdigest(),
        "review_code_sha": probe["review_code_sha"],
        "reviewer_provider": probe["reviewer_provider"],
        "reviewer_model": probe["reviewer_model"],
        "answer_providers": sorted(answer_providers),
        "same_provider_family": probe["reviewer_provider"] in answer_providers,
        "actual_clean_diagnostics": sum(case["actual_clean_diagnostic"] for case in cases),
        "target_controls_detected": sum(row["target_detected"] for row in controls),
        "specific_controls_passed": sum(row["specific"] for row in controls),
        "controls_total": len(controls),
        "specificity_gate": "pass" if specificity_pass else "fail",
        "cases": cases,
        "qualified_judge": False,
        "formal_semantic_label": False,
        "release_observation": False,
        "release_gate": "NO_GO",
    }
