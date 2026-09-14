"""Paired performance attribution harness for RQ1-C bounded qualification.

Purpose (frozen rule, PROJECT_STATUS §27): **when the environment is unstable,
performance changes may not be attributed to code**. This tool therefore runs
one structure only:

    F0 -> A1 -> F1 -> B -> F2 -> A2 -> F3

* ``A1`` / ``A2`` / ``B`` execute the *same* calibration cases, the same frozen
  budgets, and the same provider/model configuration.
* ``A`` is a baseline git ref, ``B`` is the candidate git ref; both are checked
  out into throwaway worktrees so each run is bound to an exact 40-char SHA and
  a clean tracked tree.
* ``F0``..``F3`` are environment fingerprints (``run_environment_fingerprint``).
  ``A1``/``A2`` external baselines are compared *before* any case comparison.

Outputs keep raw values, never booleans alone:

* ``external_baseline``: raw fingerprints plus ``comparison_status``
  (``stable`` | ``environment_unstable``) and ``attribution_allowed``.
* ``case_deltas``: per case, per metric, raw A1/A2/B values, the A mean and the
  B-A delta.
* ``reserve_calibration``: finalization latency (research stop -> run
  completed) p50/p90/max, so ``FINALIZATION_RESERVE_SECONDS`` can later be
  calibrated from measurement instead of guessing.

This tool never changes budgets, providers or prompts; it only measures.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "rq1c-paired-attribution-v1"
DEFAULT_MANIFEST = Path("tests/fixtures/research_quality/rq1c_bounded_holdout_manifest.json")
DEFAULT_OUTPUT_DIR = Path("docs/research_quality")
DEFAULT_CASE_TIMEOUT_SECONDS = 300.0

# Calibration cases: deliberately *existing* holdout cases (never a new
# workload) so the measured latency can feed the qualification decision.
CALIBRATION_CASES: tuple[dict[str, str], ...] = (
    {
        "label": "C1",
        "case_id": "rq1c-numeric-uk-inflation",
        "shape": "direct-primary",
        "rationale": (
            "Search reaches a primary source directly; no lead discovery and no "
            "evidence-lead follow-up was needed in the recorded holdout runs."
        ),
    },
    {
        "label": "C2",
        "case_id": "rq1c-unverifiable-python-security",
        "shape": "candidate-lead",
        "rationale": (
            "Recorded holdout runs show lead_discovery_succeeded + lead_read_started, "
            "i.e. a lead_only candidate had to be read before evidence existed."
        ),
    },
    {
        "label": "C3",
        "case_id": "rq1c-academic-primary-attention",
        "shape": "evidence-lead",
        "rationale": (
            "Recorded holdout runs show relation=lead follow-ups "
            "(evidence_lead_followup_started), i.e. a read page had to hand a "
            "deeper asset to a bounded follow-up."
        ),
    },
    {
        "label": "C4",
        "case_id": "rq1c-provenance-xz",
        "shape": "deadline-stress",
        "rationale": (
            "Recorded holdout runs show evidence_lead_followup_skipped_insufficient_budget "
            "and a run that reached the research window boundary; this is the case "
            "most sensitive to the reserved tail."
        ),
    },
)

# v1 tolerances are deliberately wide: the goal is to stop silently attributing
# environment drift to code, not to tune "too large" precisely yet.
EXTERNAL_TOLERANCES: dict[str, dict[str, float]] = {
    "deepseek": {"absolute_ms": 2000.0, "relative": 1.0},
    "provider": {"absolute_ms": 3000.0, "relative": 1.0},
    "reader": {"absolute_ms": 2000.0, "relative": 1.0},
}

_PROVIDER_KEYS = ("bing_rss", "duckduckgo_html", "searxng")


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested without network)
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError("holdout manifest must be an object with a cases list")
    return data


def select_calibration_cases(
    manifest: Mapping[str, Any],
    labels: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    """Return the requested calibration rows, failing closed on unknown ids."""

    case_ids = {
        str(case.get("id"))
        for case in manifest.get("cases", [])
        if isinstance(case, Mapping)
    }
    selected: list[dict[str, str]] = []
    for row in CALIBRATION_CASES:
        if labels and row["label"] not in labels:
            continue
        if row["case_id"] not in case_ids:
            raise ValueError(
                f"calibration case {row['label']} ({row['case_id']}) is not in the manifest"
            )
        selected.append(dict(row))
    if not selected:
        raise ValueError("no calibration case selected")
    unknown = sorted(set(labels or ()) - {row["label"] for row in CALIBRATION_CASES})
    if unknown:
        raise ValueError(f"unknown calibration labels: {', '.join(unknown)}")
    return selected


def write_case_manifest(
    manifest: Mapping[str, Any],
    case_ids: Sequence[str],
    destination: Path,
) -> Path:
    """Write a manifest restricted to the calibration cases (same schema)."""

    wanted = list(case_ids)
    cases = [
        case
        for case in manifest.get("cases", [])
        if isinstance(case, Mapping) and str(case.get("id")) in wanted
    ]
    if len(cases) != len(wanted):
        raise ValueError("calibration manifest would drop a requested case")
    payload = dict(manifest)
    payload["cases"] = cases
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile (ties round up) over a small sample.

    Deterministic and explicit rather than interpolated: with 9-12 samples a
    reported p90 should be an actually observed value, not a synthetic average.
    """

    ordered = sorted(float(item) for item in values)
    if not ordered:
        return None
    index = min(
        len(ordered) - 1,
        max(0, int(fraction * (len(ordered) - 1) + 0.5)),
    )
    return round(ordered[index], 3)


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(item) for item in values]
    return {
        "samples": [round(item, 3) for item in clean],
        "count": len(clean),
        "p50": _percentile(clean, 0.5),
        "p90": _percentile(clean, 0.9),
        "max": round(max(clean), 3) if clean else None,
    }


def project_case_artifact(case: Mapping[str, Any]) -> dict[str, Any]:
    """Project one qualification case into the attribution metric set."""

    metrics = case.get("metrics") or {}
    phases = metrics.get("phase_seconds") if isinstance(metrics, Mapping) else None
    phase_seconds = {
        str(name): round(float((value or {}).get("seconds") or 0.0), 3)
        for name, value in (phases or {}).items()
        if isinstance(value, Mapping)
    }
    phase_calls = {
        str(name): int((value or {}).get("calls") or 0)
        for name, value in (phases or {}).items()
        if isinstance(value, Mapping)
    }
    window = metrics.get("research_window") if isinstance(metrics, Mapping) else None
    research_elapsed = None
    if isinstance(window, Mapping):
        value = window.get("research_elapsed_seconds")
        research_elapsed = None if value is None else round(float(value), 3)
    total = case.get("elapsed_seconds")
    total_seconds = None if total is None else round(float(total), 3)
    finalization = None
    if total_seconds is not None and research_elapsed is not None:
        finalization = round(max(0.0, total_seconds - research_elapsed), 3)

    budget = case.get("budget_observed") or {}
    search = case.get("search") or {}
    lead = metrics.get("lead_discovery") if isinstance(metrics, Mapping) else {}
    lead = lead if isinstance(lead, Mapping) else {}
    breakdown = case.get("finalization_breakdown")
    breakdown = dict(breakdown) if isinstance(breakdown, Mapping) else {}
    return {
        "case_id": case.get("case_id"),
        "category": case.get("category"),
        "status": (case.get("run") or {}).get("status"),
        "stop_reason": (case.get("run") or {}).get("stop_reason"),
        "gate_status": (case.get("gate") or {}).get("status"),
        "elapsed_seconds": total_seconds,
        "research_elapsed_seconds": research_elapsed,
        "finalization_seconds": finalization,
        "phase_seconds": phase_seconds,
        "phase_calls": phase_calls,
        "finalization_breakdown": breakdown,
        "answer_generation_seconds": _breakdown_seconds(
            breakdown, "answer_generation_seconds"
        ),
        "answer_binding_seconds": _breakdown_seconds(
            breakdown, "answer_claim_binding_seconds"
        ),
        "answer_stage_seconds": _breakdown_seconds(breakdown, "answer_stage_seconds"),
        "unclassified_answer_seconds": _breakdown_seconds(
            breakdown, "other_seconds"
        ),
        "projection_seconds": _breakdown_seconds(
            breakdown, "post_research_projection_seconds"
        ),
        "artifact_write_seconds": _breakdown_seconds(
            breakdown, "artifact_write_seconds"
        ),
        "answer_stage_call_count": int(breakdown.get("answer_stage_call_count") or 0),
        "provider_attempts": int(search.get("attempt_count") or 0),
        "reads": int(budget.get("read_count") or 0),
        "read_attempts": int(budget.get("read_attempt_count") or 0),
        "model_calls": int(budget.get("model_call_count") or 0),
        "research_model_calls": int(budget.get("research_model_call_count") or 0),
        "answer_generation_model_calls": int(
            budget.get("answer_generation_model_call_count") or 0
        ),
        "answer_binding_model_calls": int(
            budget.get("answer_binding_model_call_count") or 0
        ),
        "support_clusters": int(metrics.get("cluster_count") or 0),
        "candidate_count": int(metrics.get("candidate_count") or 0),
        "lead_actions": {str(key): int(value) for key, value in lead.items()},
    }


def _breakdown_seconds(breakdown: Mapping[str, Any], key: str) -> float | None:
    value = breakdown.get(key)
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _fingerprint_metrics(fingerprint: Mapping[str, Any]) -> dict[str, float]:
    """Flatten one fingerprint into ``name -> milliseconds`` external latencies."""

    values: dict[str, float] = {}
    deepseek = fingerprint.get("deepseek") or {}
    for probe in ("planner", "assessor", "extractor"):
        row = deepseek.get(probe) or {}
        elapsed = row.get("elapsed_ms")
        if elapsed is not None:
            values[f"deepseek.{probe}"] = float(elapsed)
    providers = (fingerprint.get("providers") or {}).get("providers") or {}
    for provider in _PROVIDER_KEYS:
        row = providers.get(provider) or {}
        elapsed = row.get("elapsed_ms")
        if elapsed is not None:
            values[f"provider.{provider}"] = float(elapsed)
    reader = fingerprint.get("reader") or {}
    if reader.get("elapsed_ms") is not None:
        values["reader"] = float(reader["elapsed_ms"])
    return values


def _fingerprint_states(fingerprint: Mapping[str, Any]) -> dict[str, str]:
    states: dict[str, str] = {}
    providers = (fingerprint.get("providers") or {}).get("providers") or {}
    for provider in _PROVIDER_KEYS:
        row = providers.get(provider) or {}
        states[provider] = f"{row.get('status')}:{row.get('reason')}"
    return states


def _tolerance_for(metric: str) -> dict[str, float]:
    if metric.startswith("deepseek."):
        return EXTERNAL_TOLERANCES["deepseek"]
    if metric.startswith("provider."):
        return EXTERNAL_TOLERANCES["provider"]
    return EXTERNAL_TOLERANCES["reader"]


def compare_external_baseline(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> dict[str, Any]:
    """Deterministically compare two fingerprints (A1 vs A2 ambient state)."""

    first_values = _fingerprint_metrics(first)
    second_values = _fingerprint_metrics(second)
    drifts: list[dict[str, Any]] = []
    for metric in sorted(set(first_values) | set(second_values)):
        left = first_values.get(metric)
        right = second_values.get(metric)
        if left is None or right is None:
            drifts.append(
                {
                    "metric": metric,
                    "first_ms": left,
                    "second_ms": right,
                    "reason": "metric_missing_on_one_side",
                }
            )
            continue
        tolerance = _tolerance_for(metric)
        delta = abs(left - right)
        relative = delta / max(1.0, min(left, right))
        if delta > tolerance["absolute_ms"] and relative > tolerance["relative"]:
            drifts.append(
                {
                    "metric": metric,
                    "first_ms": left,
                    "second_ms": right,
                    "delta_ms": round(delta, 1),
                    "relative": round(relative, 3),
                    "tolerance": dict(tolerance),
                }
            )
    first_states = _fingerprint_states(first)
    second_states = _fingerprint_states(second)
    material_changes = [
        {
            "provider": provider,
            "first": first_states.get(provider),
            "second": second_states.get(provider),
        }
        for provider in sorted(set(first_states) | set(second_states))
        if first_states.get(provider) != second_states.get(provider)
    ]
    errors = list(first.get("errors") or []) + list(second.get("errors") or [])
    unstable = bool(drifts or material_changes or errors)
    return {
        "status": "environment_unstable" if unstable else "stable",
        "attribution_allowed": not unstable,
        "drifts": drifts,
        "material_provider_changes": material_changes,
        "fingerprint_errors": errors,
    }


_METRIC_DIRECTIONS: dict[str, str] = {
    "elapsed_seconds": "lower_is_better",
    "research_elapsed_seconds": "lower_is_better",
    "finalization_seconds": "lower_is_better",
    "answer_generation_seconds": "lower_is_better",
    "answer_binding_seconds": "lower_is_better",
    "answer_stage_seconds": "lower_is_better",
    "projection_seconds": "lower_is_better",
    "artifact_write_seconds": "lower_is_better",
    "provider_attempts": "lower_is_better",
    "reads": "lower_is_better",
    "read_attempts": "lower_is_better",
    "model_calls": "lower_is_better",
    "research_model_calls": "lower_is_better",
    "answer_generation_model_calls": "lower_is_better",
    "answer_binding_model_calls": "lower_is_better",
    "support_clusters": "higher_is_better",
    "candidate_count": "higher_is_better",
}


def summarize_case_deltas(
    baseline_runs: Sequence[Mapping[str, Any]],
    candidate_run: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Per case, per metric: raw samples plus p50/p90/max for A and B.

    Distributions are reported instead of a single mean because a single
    finalization run already varies by ~10s; a difference is only meaningful
    against that spread.
    """

    by_case: dict[str, list[dict[str, Any]]] = {}
    for run in baseline_runs:
        for projection in run.get("cases", []):
            by_case.setdefault(str(projection.get("case_id")), []).append(projection)
    candidate_by_case: dict[str, list[dict[str, Any]]] = {}
    for projection in candidate_run.get("cases", []):
        candidate_by_case.setdefault(str(projection.get("case_id")), []).append(projection)
    rows: list[dict[str, Any]] = []
    for case_id in sorted(set(by_case) | set(candidate_by_case)):
        baseline = by_case.get(case_id, [])
        candidate = candidate_by_case.get(case_id, [])
        metrics: dict[str, Any] = {}
        for metric, direction in _METRIC_DIRECTIONS.items():
            baseline_values = [
                float(item[metric])
                for item in baseline
                if item.get(metric) is not None
            ]
            candidate_values = [
                float(item[metric])
                for item in candidate
                if item.get(metric) is not None
            ]
            baseline_stats = _distribution(baseline_values)
            candidate_stats = _distribution(candidate_values)
            delta = (
                round(candidate_stats["p50"] - baseline_stats["p50"], 3)
                if candidate_stats["p50"] is not None
                and baseline_stats["p50"] is not None
                else None
            )
            metrics[metric] = {
                "baseline": baseline_stats,
                "candidate": candidate_stats,
                "delta_p50": delta,
                "direction": direction,
            }
        baseline_phases = [item.get("phase_seconds") or {} for item in baseline]
        candidate_phases = [item.get("phase_seconds") or {} for item in candidate]
        phase_rows: dict[str, Any] = {}
        for phase in sorted(
            {key for item in baseline_phases for key in item}
            | {key for item in candidate_phases for key in item}
        ):
            values = [
                float(item[phase])
                for item in baseline_phases
                if item.get(phase) is not None
            ]
            candidate_values = [
                float(item[phase])
                for item in candidate_phases
                if item.get(phase) is not None
            ]
            phase_rows[phase] = {
                "baseline": _distribution(values),
                "candidate": _distribution(candidate_values),
            }
        rows.append(
            {
                "case_id": case_id,
                "baseline_statuses": [item.get("status") for item in baseline],
                "candidate_statuses": [item.get("status") for item in candidate],
                "baseline_gate_statuses": [item.get("gate_status") for item in baseline],
                "candidate_gate_statuses": [item.get("gate_status") for item in candidate],
                "baseline_stop_reasons": [item.get("stop_reason") for item in baseline],
                "candidate_stop_reasons": [item.get("stop_reason") for item in candidate],
                "lead_actions": {
                    "baseline_runs": [item.get("lead_actions") for item in baseline],
                    "candidate_runs": [item.get("lead_actions") for item in candidate],
                },
                "metrics": metrics,
                "phases": phase_rows,
            }
        )
    return rows


def summarize_reserve_calibration(
    runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Finalization distributions (research stop -> run completed).

    Reports the real steps: research, projection, answer stage (split into
    answer_generation / answer_claim_binding), artifact write and the residual.
    A reserve calibrated from p90 needs several samples per ref, so the sample
    count and adequacy flag travel with the numbers.
    """

    keys = {
        "finalization": "finalization_seconds",
        "research": "research_elapsed_seconds",
        "answer_generation": "answer_generation_seconds",
        "answer_binding": "answer_binding_seconds",
        "answer_stage": "answer_stage_seconds",
        "projection": "projection_seconds",
        "artifact_write": "artifact_write_seconds",
    }
    samples: dict[str, list[float]] = {name: [] for name in keys}
    for run in runs:
        for projection in run.get("cases", []):
            for name, metric in keys.items():
                value = projection.get(metric)
                if value is not None:
                    samples[name].append(float(value))
    finalization = samples["finalization"]
    return {
        "sample_count": len(finalization),
        "distributions": {name: _distribution(values) for name, values in samples.items()},
        "finalization_p50_seconds": _percentile(finalization, 0.5),
        "finalization_p90_seconds": _percentile(finalization, 0.9),
        "finalization_max_seconds": max(finalization) if finalization else None,
        "research_p50_seconds": _percentile(samples["research"], 0.5),
        "research_max_seconds": max(samples["research"]) if samples["research"] else None,
        "sample_adequate_for_reserve": len(finalization) >= 6,
        "note": (
            "A reserve calibrated from p90 needs several samples per ref; keep "
            "FINALIZATION_RESERVE_SECONDS unchanged until the breakdown says which "
            "step actually dominates."
        ),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


class HarnessError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise HarnessError(
            f"git {' '.join(args)} failed: {completed.stderr.strip() or completed.returncode}"
        )
    return completed.stdout.strip()


def _resolve_commit(repo: Path, ref: str) -> str:
    value = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").lower()
    if len(value) != 40:
        raise HarnessError(f"ref is not an exact commit sha: {ref}")
    return value


def _git_env(repo: Path) -> dict[str, str]:
    env = dict(os.environ)
    # The worktree HEAD is the identity we record; a parent GITHUB_SHA would
    # belong to a different checkout and must not leak into the child run.
    env.pop("GITHUB_SHA", None)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        from dotenv import dotenv_values

        for key, value in dotenv_values(repo / ".env").items():
            if value is not None and key not in env:
                env[key] = value
    except Exception:  # pragma: no cover - optional convenience only
        pass
    return env


MEASUREMENT_RUNNER = Path("tools/run_rq1c_calibration.py")


def _install_measurement_runner(worktree: Path, repo: Path) -> str:
    """Make the calibration-case runner available inside a worktree.

    The strict qualification entrypoint is frozen to 12 holdout cases, so paired
    attribution drives a diagnostic subset through a dedicated runner. A ref
    that predates that runner gets the harness's own copy *as an untracked
    file* - the worktree's tracked tree stays exactly at the ref, which is what
    the exact-head guard checks. A ref that already ships the runner keeps its
    own copy so the measured code is the ref's code.
    """

    destination = worktree / MEASUREMENT_RUNNER
    if destination.exists():
        return "checkout"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        (repo / MEASUREMENT_RUNNER).read_text(encoding="utf-8"), encoding="utf-8"
    )
    return "injected"


def _run_case(
    *,
    worktree: Path,
    manifest: Path,
    case_id: str,
    output: Path,
    timeout_seconds: float,
    env: Mapping[str, str],
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.run_rq1c_calibration",
                "--manifest",
                str(manifest),
                "--cases",
                case_id,
                "--output",
                str(output),
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=dict(env),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "harness_timeout",
            "elapsed_seconds": timeout_seconds,
            "started_at": started.isoformat(),
            "stdout_tail": "",
            "stderr_tail": "harness case timeout",
        }
    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "elapsed_seconds": round(
            (datetime.now(timezone.utc) - started).total_seconds(), 3
        ),
        "started_at": started.isoformat(),
        "stdout_tail": completed.stdout[-2000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def _run_fingerprint(output: Path, env: Mapping[str, str], repo: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.run_environment_fingerprint",
            "--output",
            str(output),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=600,
        env=dict(env),
    )
    if completed.returncode != 0:
        raise HarnessError(
            f"fingerprint failed: {completed.stderr.strip() or completed.returncode}"
        )
    return json.loads(output.read_text(encoding="utf-8"))


def _load_case_artifacts(
    directory: Path, case_ids: Sequence[str], repeats: int
) -> dict[str, Any]:
    """Project the per-case calibration artifacts written by one execution."""

    projections: list[dict[str, Any]] = []
    missing: list[str] = []
    for case_id in case_ids:
        found = False
        for repeat in range(1, max(1, repeats) + 1):
            suffix = "" if repeats <= 1 else f"__r{repeat}"
            path = directory / f"{case_id}{suffix}.json"
            if not path.exists():
                missing.append(f"{case_id}{suffix}")
                continue
            artifact = json.loads(path.read_text(encoding="utf-8"))
            case = next(
                (
                    item
                    for item in artifact.get("cases", [])
                    if str(item.get("case_id")) == case_id
                ),
                None,
            )
            if case is None:
                missing.append(f"{case_id}{suffix}")
                continue
            found = True
            projections.append(project_case_artifact(case))
        if not found:
            missing.append(case_id)
    return {"cases": projections, "missing_cases": missing}


def run_paired_attribution(
    *,
    repo: Path,
    baseline_ref: str,
    candidate_ref: str,
    labels: Sequence[str] | None = None,
    output: Path,
    workdir: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
    case_timeout_seconds: float = DEFAULT_CASE_TIMEOUT_SECONDS,
    repeats: int = 1,
    keep_worktrees: bool = False,
) -> dict[str, Any]:
    baseline_sha = _resolve_commit(repo, baseline_ref)
    candidate_sha = _resolve_commit(repo, candidate_ref)
    if baseline_sha == candidate_sha:
        raise HarnessError("baseline and candidate resolve to the same commit")

    manifest = load_manifest(repo / manifest_path)
    selected = select_calibration_cases(manifest, labels)
    case_ids = [row["case_id"] for row in selected]

    workdir.mkdir(parents=True, exist_ok=True)
    env = _git_env(repo)

    worktrees: dict[str, Path] = {}
    runner_sources: dict[str, str] = {}
    for label, sha in (("baseline", baseline_sha), ("candidate", candidate_sha)):
        path = workdir / f"wt_{label}"
        if path.exists():
            shutil.rmtree(path)
        _git(repo, "worktree", "add", "--detach", str(path), sha)
        worktrees[label] = path
        runner_sources[label] = _install_measurement_runner(path, repo)

    runs: dict[str, dict[str, Any]] = {}
    fingerprints: list[dict[str, Any]] = []
    try:
        fingerprints.append(
            {"label": "F0", "artifact": _run_fingerprint(workdir / "fingerprint.F0.json", env, repo)}
        )

        for label, worktree, fingerprint_label in (
            ("A1", worktrees["baseline"], "F1"),
            ("B", worktrees["candidate"], "F2"),
            ("A2", worktrees["baseline"], "F3"),
        ):
            run_dir = workdir / label
            runs[label] = {
                "ref": baseline_sha if label.startswith("A") else candidate_sha,
                "case_runs": {},
            }
            for case_id in case_ids:
                for repeat in range(1, max(1, repeats) + 1):
                    suffix = "" if repeats <= 1 else f"__r{repeat}"
                    result = _run_case(
                        worktree=worktree,
                        manifest=(repo / manifest_path).resolve(),
                        case_id=case_id,
                        output=run_dir / f"{case_id}{suffix}.json",
                        timeout_seconds=case_timeout_seconds,
                        env=env,
                    )
                    runs[label]["case_runs"][f"{case_id}{suffix}"] = result
            runs[label].update(
                _load_case_artifacts(run_dir, case_ids, repeats)
            )
            fingerprints.append(
                {
                    "label": fingerprint_label,
                    "artifact": _run_fingerprint(
                        workdir / f"fingerprint.{fingerprint_label}.json", env, repo
                    ),
                }
            )
    finally:
        if not keep_worktrees:
            for path in worktrees.values():
                try:
                    _git(repo, "worktree", "remove", "--force", str(path))
                except HarnessError:  # pragma: no cover - best effort cleanup
                    shutil.rmtree(path, ignore_errors=True)

    by_label = {item["label"]: item["artifact"] for item in fingerprints}
    external = compare_external_baseline(by_label["F1"], by_label["F3"])
    deltas = summarize_case_deltas([runs["A1"], runs["A2"]], runs["B"])
    reserve = summarize_reserve_calibration([runs["A1"], runs["B"], runs["A2"]])

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": {"ref": baseline_ref, "sha": baseline_sha},
        "candidate": {"ref": candidate_ref, "sha": candidate_sha},
        "calibration_cases": selected,
        "case_timeout_seconds": case_timeout_seconds,
        "repeats_per_ref_per_case": max(1, repeats),
        "external_tolerances": EXTERNAL_TOLERANCES,
        "measurement_runner": {
            "path": MEASUREMENT_RUNNER.as_posix(),
            "sources": runner_sources,
            "qualification_guard": (
                "the strict 12-case qualification entrypoint is untouched; this "
                "runner drives a diagnostic subset of the same frozen manifest"
            ),
        },
        "fingerprints": {
            item["label"]: item["artifact"] for item in fingerprints
        },
        "external_baseline": {
            "compared": ["F1", "F3"],
            **external,
        },
        "comparison_status": external["status"],
        "attribution_allowed": external["attribution_allowed"],
        "runs": {
            label: {
                "ref": run["ref"],
                "case_runs": run["case_runs"],
                "cases": run["cases"],
                "missing_cases": run["missing_cases"],
            }
            for label, run in runs.items()
        },
        "case_deltas": deltas,
        "reserve_calibration": reserve,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument(
        "--cases",
        default="",
        help="comma separated calibration labels (default: all of C1..C4)",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument(
        "--case-timeout-seconds",
        type=float,
        default=DEFAULT_CASE_TIMEOUT_SECONDS,
    )
    parser.add_argument("--keep-worktrees", action="store_true")
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="runs per ref per case (>=3 gives a usable p50/p90 distribution)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo = args.repo.resolve()
    labels = [item.strip() for item in args.cases.split(",") if item.strip()]
    candidate_sha = _resolve_commit(repo, args.candidate_ref)
    output = (
        args.output.resolve()
        if args.output
        else (repo / DEFAULT_OUTPUT_DIR / f"PAIRED_ATTRIBUTION.{candidate_sha[:8]}.json")
    )
    workdir = (
        args.workdir.resolve()
        if args.workdir
        else Path(tempfile.mkdtemp(prefix="rq1c_paired_"))
    )
    artifact = run_paired_attribution(
        repo=repo,
        baseline_ref=args.baseline_ref,
        candidate_ref=args.candidate_ref,
        labels=labels or None,
        output=output,
        workdir=workdir,
        manifest_path=args.manifest,
        case_timeout_seconds=args.case_timeout_seconds,
        repeats=max(1, args.repeats),
        keep_worktrees=args.keep_worktrees,
    )
    summary = {
        "comparison_status": artifact["comparison_status"],
        "attribution_allowed": artifact["attribution_allowed"],
        "drift_count": len(artifact["external_baseline"]["drifts"]),
        "material_provider_changes": len(
            artifact["external_baseline"]["material_provider_changes"]
        ),
        "baseline_sha": artifact["baseline"]["sha"],
        "candidate_sha": artifact["candidate"]["sha"],
        "repeats_per_ref_per_case": artifact["repeats_per_ref_per_case"],
        "cases": [
            {
                "case_id": row["case_id"],
                "baseline_elapsed": row["metrics"]["elapsed_seconds"]["baseline"],
                "candidate_elapsed": row["metrics"]["elapsed_seconds"]["candidate"],
                "baseline_finalization": row["metrics"]["finalization_seconds"][
                    "baseline"
                ],
                "candidate_finalization": row["metrics"]["finalization_seconds"][
                    "candidate"
                ],
                "delta_finalization_p50": row["metrics"]["finalization_seconds"][
                    "delta_p50"
                ],
                "delta_support_clusters_p50": row["metrics"]["support_clusters"][
                    "delta_p50"
                ],
            }
            for row in artifact["case_deltas"]
        ],
        "reserve_calibration": artifact["reserve_calibration"],
        "output": str(output),
    }
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
