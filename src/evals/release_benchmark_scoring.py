"""Score recorded release observations without granting release approval.

Execution, human labels, judge qualification, and thresholds are external
authorities. Missing evidence remains visible in every denominator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from src.evals.release_benchmark_plan import ReleaseBenchmarkPlan, plan_digest
from src.evals.release_benchmark_registry import (
    ReleaseCase,
    ReleaseGold,
    ReleaseRegistry,
    _object,
    _read_json,
    _text,
    _text_list,
    _timestamp,
    admission_report,
    canonical_digest,
)

OBSERVATION_SCHEMA_VERSION = "release-benchmark-observation-v1"
SCORE_SCHEMA_VERSION = "release-benchmark-score-v1"
METRICS = (
    "original_source_recall", "read_success", "required_unit_coverage",
    "conflict_preservation", "visual_value", "question_coverage",
    "evidence_grounding", "citation_support", "auditor_accuracy",
    "answer_utility", "latency_seconds", "attributed_cost",
)
SEMANTIC_METRICS = {
    "conflict_preservation", "visual_value", "question_coverage",
    "evidence_grounding", "citation_support", "auditor_accuracy", "answer_utility",
}
HARD_FAILURES = {
    "unsupported_strong_assertion", "wrong_citation", "false_settled_conflict",
    "unauthorized_confirmed", "stale_memory_as_evidence", "cross_thread_leak",
}
_SHA = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class MetricLabel:
    state: str
    value: float | None
    unit: str | None
    reason: str | None
    evidence_refs: tuple[str, ...]
    assessor_kind: str
    assessor_id: str | None


@dataclass(frozen=True)
class CaseObservation:
    case_id: str
    state: str
    reason: str | None
    source_reads: tuple[SourceRead, ...]
    metrics: tuple[tuple[str, MetricLabel], ...]
    hard_failures: tuple[HardFailure, ...]


@dataclass(frozen=True)
class SourceRead:
    source_id: str
    locator: str
    state: str
    reason: str | None
    observed_at: str
    page: int | None
    region: str | None
    human_reviewed_by: str | None


@dataclass(frozen=True)
class HardFailure:
    code: str
    reason: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class RecordedRun:
    code_sha: str
    mode: str
    cases: tuple[CaseObservation, ...]
    captured_at: str
    plan_digest: str
    registry_digest: str
    gold_digest: str
    execution_kind: str
    network_disabled: bool
    recording_digest: str
    configuration_digest: str
    started_at: str
    ended_at: str


def eligible_metrics(case: ReleaseCase) -> tuple[str, ...]:
    return tuple(metric for metric in METRICS if (
        metric != "conflict_preservation" or bool(case.expected_conflicts)
    ) and (
        metric != "visual_value" or case.visual_evidence_required
    ) and (
        metric != "auditor_accuracy" or case.primary_focus == "auditor"
    ))


def load_recording(path: str | Path, plan: ReleaseBenchmarkPlan,
                   registry: ReleaseRegistry, gold: ReleaseGold,
                   expected_code_sha: str) -> RecordedRun:
    return parse_recording(_read_json(path, "release observation"),
                           plan, registry, gold, expected_code_sha)


def parse_recording(raw: Any, plan: ReleaseBenchmarkPlan,
                    registry: ReleaseRegistry, gold: ReleaseGold,
                    expected_code_sha: str) -> RecordedRun:
    data = _object(raw, {
        "schema_version", "code_sha", "plan_digest", "registry_digest", "gold_digest",
        "mode", "captured_at", "execution_kind", "network_disabled", "configuration",
        "reader_flags", "budgets", "model_versions", "tool_versions", "time_window",
        "cases",
    }, "release observation")
    if data["schema_version"] != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("unsupported release observation schema")
    code_sha = data["code_sha"]
    if (not isinstance(code_sha, str) or not _SHA.fullmatch(code_sha)
            or code_sha != expected_code_sha):
        raise ValueError("release observation code SHA mismatch")
    if (data["plan_digest"] != plan_digest(plan)
            or data["registry_digest"] != registry.digest
            or data["gold_digest"] != gold.digest):
        raise ValueError("release observation manifest or gold digest mismatch")
    mode = data["mode"]
    if mode not in {"frozen", "live"}:
        raise ValueError("invalid release observation mode")
    if mode == "frozen":
        if data["execution_kind"] != "offline_replay" or data["network_disabled"] is not True:
            raise ValueError("frozen replay must declare offline execution")
    elif data["execution_kind"] != "manual_live" or data["network_disabled"] is not False:
        raise ValueError("live observations require manual live execution")
    for key in ("configuration", "reader_flags", "budgets", "model_versions", "tool_versions"):
        value = data[key]
        if not isinstance(value, dict) or not value:
            raise ValueError(f"release observation requires {key}")
        if any(not isinstance(name, str) or not name.strip() or
               re.search(r"api[_-]?key|secret|token|password", name, re.IGNORECASE) or
               not isinstance(item, (str, int, float, bool)) or item == "" or
               (isinstance(item, str) and len(item) > 200)
               for name, item in value.items()):
            raise ValueError(f"invalid release observation {key}")
    window = _object(data["time_window"], {"started_at", "ended_at"}, "time window")
    start = _timestamp(window["started_at"], "run start")
    end = _timestamp(window["ended_at"], "run end")
    if datetime.fromisoformat(end.replace("Z", "+00:00")) < datetime.fromisoformat(
        start.replace("Z", "+00:00")
    ):
        raise ValueError("release observation time window reversed")
    captured = _timestamp(data["captured_at"], "observation capture time")
    rows = data["cases"]
    if not isinstance(rows, list):
        raise ValueError("invalid release observation cases")
    known = {case.case_id: case for case in registry.cases if case.mode == mode}
    observations = tuple(_parse_case_observation(row, known, start, end) for row in rows)
    ids = [case.case_id for case in observations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate release observation case")
    return RecordedRun(code_sha, mode, observations, captured, data["plan_digest"],
                       data["registry_digest"], data["gold_digest"],
                       data["execution_kind"], data["network_disabled"],
                       canonical_digest(data), canonical_digest({
                           key: data[key] for key in (
                               "configuration", "reader_flags", "budgets",
                               "model_versions", "tool_versions",
                           )
                       }), start, end)


def _parse_case_observation(raw: Any, cases: dict[str, ReleaseCase],
                            started_at: str, ended_at: str) -> CaseObservation:
    data = _object(raw, {
        "case_id", "state", "reason", "source_reads", "metrics", "hard_failures",
    }, "case observation")
    case = cases.get(data["case_id"])
    if case is None:
        raise ValueError("observation references unknown or wrong-mode case")
    state = data["state"]
    if state not in {"completed", "unavailable", "failure"}:
        raise ValueError("invalid case observation state")
    reason = data["reason"]
    if state == "completed":
        if reason is not None:
            raise ValueError("completed observation cannot have failure reason")
    else:
        reason = _text(reason, "observation failure reason", 500)
    if not isinstance(data["source_reads"], list):
        raise ValueError("invalid release source reads")
    reads = tuple(_parse_source_read(item, case, started_at, ended_at)
                  for item in data["source_reads"])
    if len({read.source_id for read in reads}) != len(reads):
        raise ValueError("duplicate release source read")
    read_ok_ids = {read.source_id for read in reads if read.state == "read_ok"}
    labels = data["metrics"]
    if (not isinstance(labels, dict) or not set(labels) <= set(eligible_metrics(case))
            or set(labels) & {"original_source_recall", "read_success"}):
        raise ValueError("observation metric is not eligible")
    if state != "completed" and labels:
        raise ValueError("unavailable case cannot carry metric labels")
    if not isinstance(data["hard_failures"], list):
        raise ValueError("invalid release hard failures")
    failures = tuple(_parse_hard_failure(item, case) for item in data["hard_failures"])
    if len({failure.code for failure in failures}) != len(failures):
        raise ValueError("duplicate release hard failure")
    return CaseObservation(case.case_id, state, reason, reads,
                           tuple((name, _parse_metric(value, name, case, read_ok_ids))
                                 for name, value in labels.items()), failures)


def _parse_source_read(raw: Any, case: ReleaseCase,
                       started_at: str, ended_at: str) -> SourceRead:
    data = _object(raw, {
        "source_id", "locator", "state", "reason", "observed_at", "page", "region",
        "human_reviewed_by",
    }, "release source read")
    source = next((item for item in case.sources if item.source_id == data["source_id"]), None)
    if source is None or data["locator"] != source.locator:
        raise ValueError("source read does not match registered locator")
    state = data["state"]
    if state not in {"read_ok", "read_failed", "snippet_only"}:
        raise ValueError("invalid release source read state")
    reason = data["reason"]
    if state == "read_ok":
        if reason is not None:
            raise ValueError("successful read cannot have failure reason")
    else:
        reason = _text(reason, "source read failure reason", 500)
    observed_at = _timestamp(data["observed_at"], "source read time")
    instant = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    if not (datetime.fromisoformat(started_at.replace("Z", "+00:00")) <= instant <=
            datetime.fromisoformat(ended_at.replace("Z", "+00:00"))):
        raise ValueError("source read time outside run window")
    page, region = data["page"], data["region"]
    if page is not None and (type(page) is not int or page < 1):
        raise ValueError("invalid release source read page")
    if region is not None:
        region = _text(region, "source read region", 300)
    reviewer = data["human_reviewed_by"]
    if case.mode == "live" and state == "read_ok":
        reviewer = _text(reviewer, "live source reviewer", 100)
        if case.visual_evidence_required and (page is None or region is None):
            raise ValueError("live visual source read needs page and region")
    elif reviewer is not None:
        reviewer = _text(reviewer, "source reviewer", 100)
    if case.mode == "frozen" and (page != source.page or region != source.region):
        raise ValueError("frozen source read locator differs from snapshot")
    return SourceRead(source.source_id, source.locator, state, reason, observed_at, page, region,
                      reviewer)


def _parse_hard_failure(raw: Any, case: ReleaseCase) -> HardFailure:
    data = _object(raw, {"code", "reason", "evidence_refs"}, "release hard failure")
    code = data["code"]
    if code not in HARD_FAILURES:
        raise ValueError("unknown release hard failure")
    refs = _text_list(data["evidence_refs"], "hard failure evidence refs", required=True)
    if not set(refs) <= {source.source_id for source in case.sources}:
        raise ValueError("hard failure cites unknown source")
    return HardFailure(code, _text(data["reason"], "hard failure reason", 500), refs)


def _parse_metric(raw: Any, name: str, case: ReleaseCase,
                  read_ok_ids: set[str]) -> MetricLabel:
    data = _object(raw, {
        "state", "value", "unit", "reason", "evidence_refs", "assessor_kind", "assessor_id",
    }, "metric label")
    state = data["state"]
    if state not in {"observed", "unavailable", "failure"}:
        raise ValueError("invalid metric state")
    value = data["value"]
    unit = data["unit"]
    reason = data["reason"]
    if state == "observed":
        if type(value) not in {int, float} or reason is not None:
            raise ValueError("observed metric needs a numeric value")
        if name == "latency_seconds":
            valid = unit == "seconds" and value >= 0
        elif name == "attributed_cost":
            valid = unit in {"CNY", "USD"} and value >= 0
        else:
            valid = unit == "ratio" and 0 <= value <= 1
        if not valid:
            raise ValueError("observed metric value or unit mismatch")
        value = float(value)
    else:
        if value is not None or unit is not None:
            raise ValueError("unobserved metric cannot have a value or unit")
        reason = _text(reason, "metric unavailable reason", 500)
    refs = _text_list(data["evidence_refs"], "metric evidence refs")
    if not set(refs) <= read_ok_ids:
        raise ValueError("metric cites unknown or unread source")
    if state == "observed" and name in SEMANTIC_METRICS and not refs:
        raise ValueError("observed semantic metric needs read-backed evidence refs")
    kind, assessor = data["assessor_kind"], data["assessor_id"]
    if state == "observed":
        allowed = {"manual", "qualified_judge"} if name in SEMANTIC_METRICS else {
            "deterministic", "manual",
        }
        if kind not in allowed:
            raise ValueError("semantic metrics require external adjudication")
        assessor = _text(assessor, "metric assessor", 100)
    elif kind != "none" or assessor is not None:
        raise ValueError("unobserved metric cannot claim an assessor")
    return MetricLabel(state, value, unit, reason, refs, kind, assessor)


def score_recordings(plan: ReleaseBenchmarkPlan, registry: ReleaseRegistry,
                     gold: ReleaseGold, recordings: tuple[RecordedRun, ...]) -> dict[str, object]:
    """Score reviewed pilot candidates; never turn self-reported labels into GO."""
    if len({run.mode for run in recordings}) != len(recordings):
        raise ValueError("duplicate release observation mode")
    if len({run.code_sha for run in recordings}) > 1:
        raise ValueError("mixed release observation code SHA")
    if any(run.plan_digest != plan_digest(plan) or run.registry_digest != registry.digest
           or run.gold_digest != gold.digest for run in recordings):
        raise ValueError("recording provenance differs from release manifests")
    if any(run.mode not in {"frozen", "live"} or
           (run.mode == "frozen") != run.network_disabled or
           run.execution_kind != ("offline_replay" if run.mode == "frozen" else "manual_live")
           for run in recordings):
        raise ValueError("recording execution mode differs from network boundary")
    admission = admission_report(plan, registry, gold)
    reviewed = {review.case_id for review in gold.reviews if review.structurally_reviewed}
    reviews = {review.case_id: review for review in gold.reviews}
    seen = {case.case_id: case for run in recordings for case in run.cases}
    unreviewed = set(seen) - reviewed
    if unreviewed:
        raise ValueError("release scoring cannot consume unreviewed candidates")
    cases: list[dict[str, Any]] = []
    for case in registry.cases:
        if case.case_id not in reviewed:
            continue
        observed = seen.get(case.case_id)
        labels = dict(observed.metrics) if observed else {}
        if observed is not None:
            labels.update(_mechanical_labels(observed, reviews[case.case_id].unit_sources))
        metrics: dict[str, dict[str, Any]] = {}
        for metric in eligible_metrics(case):
            label = labels.get(metric)
            if label is not None:
                metrics[metric] = {
                    "state": label.state, "value": label.value, "unit": label.unit,
                    "reason": label.reason, "evidence_refs": list(label.evidence_refs),
                    "assessor_kind": label.assessor_kind, "assessor_id": label.assessor_id,
                }
            else:
                metrics[metric] = {
                    "state": "failure" if observed and observed.state == "failure" else "unavailable",
                    "value": None, "unit": None,
                    "reason": observed.reason if observed and observed.reason else (
                        "metric_not_recorded" if observed else "observation_missing"
                    ),
                    "evidence_refs": [], "assessor_kind": "none", "assessor_id": None,
                }
        cases.append({
            "case_id": case.case_id, "mode": case.mode, "modality": case.modality,
            "primary_focus": case.primary_focus, "release_admitted": False,
            "state": observed.state if observed else "missing",
            "reason": observed.reason if observed else "observation_missing",
            "source_reads": [
                {"source_id": read.source_id, "locator": read.locator,
                 "state": read.state, "reason": read.reason,
                 "observed_at": read.observed_at,
                 "page": read.page, "region": read.region,
                 "human_reviewed_by": read.human_reviewed_by}
                for read in observed.source_reads
            ] if observed else [],
            "metrics": metrics,
            "hard_failures": [
                {"code": failure.code, "reason": failure.reason,
                 "evidence_refs": list(failure.evidence_refs)}
                for failure in observed.hard_failures
            ] if observed else [],
        })
    hard_failures = [{"case_id": item["case_id"], **failure}
                     for item in cases for failure in item["hard_failures"]]
    strata = {
        "mode": {mode: _stratum(cases, mode, sum(cell.count for cell in plan.cells
                                                if cell.mode == mode), "mode")
                 for mode in ("frozen", "live")},
        "modality": {modality: _stratum(cases, modality, sum(cell.count for cell in plan.cells
                                                            if cell.modality == modality),
                                         "modality")
                     for modality in ("text", "pdf", "image", "chart", "mixed")},
        "primary_focus": {focus: _stratum(cases, focus, target, "primary_focus")
                          for focus, target in plan.focus_targets},
    }
    hard_failure_counts = {code: sum(item["code"] == code for item in hard_failures)
                           for code in sorted(HARD_FAILURES)}
    return {
        "schema_version": SCORE_SCHEMA_VERSION,
        "code_sha": recordings[0].code_sha if recordings else None,
        "recordings": [
            {"mode": run.mode, "execution_kind": run.execution_kind,
             "network_disabled": run.network_disabled,
             "recording_digest": run.recording_digest,
             "configuration_digest": run.configuration_digest,
             "started_at": run.started_at, "ended_at": run.ended_at,
             "captured_at": run.captured_at}
            for run in recordings
        ],
        "plan_digest": plan_digest(plan), "registry_digest": registry.digest,
        "gold_digest": gold.digest, "target_denominator": plan.target_total,
        "registered_cases": admission["registered_cases"],
        "reviewed_candidate_cases": admission["reviewed_candidate_cases"],
        "admission_basis": admission["admission_basis"],
        "admitted_release_cases": admission["admitted_release_cases"],
        "unadmitted_cases": admission["missing_release_cases"],
        "missing_observations": sum(item["state"] == "missing" for item in cases),
        "metrics": _metric_summary(cases), "strata": strata, "cases": cases,
        "hard_failures": hard_failures, "hard_failure_counts": hard_failure_counts,
        "release_gate": "NO_GO",
        "reasons": [
            *(["release_cases_incomplete"] if admission["missing_release_cases"] else []),
            *(["release_observations_incomplete"]
              if any(item["state"] == "missing" for item in cases) else []),
            "release_thresholds_and_judge_qualification_not_locked",
            *(["hard_safety_error"] if hard_failures else []),
        ],
    }


def _mechanical_labels(
    observed: CaseObservation,
    unit_sources: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, MetricLabel]:
    read_ok = {read.source_id for read in observed.source_reads if read.state == "read_ok"}
    relevant = {source_id for _, source_ids in unit_sources for source_id in source_ids}
    recall = len(read_ok & relevant) / len(relevant)
    result = {
        "original_source_recall": MetricLabel(
            "observed", recall, "ratio", None, tuple(sorted(read_ok & relevant)),
            "deterministic", "source-read-recall-v1",
        ),
    }
    if observed.source_reads:
        result["read_success"] = MetricLabel(
            "observed", len(read_ok) / len(observed.source_reads), "ratio", None,
            tuple(sorted(read_ok)), "deterministic", "source-read-success-v1",
        )
    else:
        result["read_success"] = MetricLabel(
            "unavailable", None, None, "no_read_attempts", (), "none", None,
        )
    return result


def _stratum(cases: list[dict[str, Any]], value: str, target: int,
             key: str) -> dict[str, object]:
    selected = [case for case in cases if case[key] == value]
    return {
        "planned": target, "reviewed_candidates": len(selected),
        "unadmitted": target - len(selected),
        "completed": sum(case["state"] == "completed" for case in selected),
        "missing": sum(case["state"] == "missing" for case in selected),
        "metrics": _metric_summary(selected),
    }


def _metric_summary(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {
        name: {"eligible": 0, "observed": 0, "unavailable": 0,
               "failure": 0, "values_by_unit": {}} for name in METRICS
    }
    for case in cases:
        for name, label in case["metrics"].items():
            summary = totals[name]
            summary["eligible"] += 1
            summary[label["state"]] += 1
            if label["state"] == "observed":
                unit = label["unit"]
                bucket = summary["values_by_unit"].setdefault(unit, {"count": 0, "sum": 0.0})
                bucket["count"] += 1
                bucket["sum"] += label["value"]
    for summary in totals.values():
        for bucket in summary["values_by_unit"].values():
            bucket["mean_observed"] = bucket["sum"] / bucket["count"]
    return totals
