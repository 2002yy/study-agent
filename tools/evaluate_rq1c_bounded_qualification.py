"""Evaluate an RQ1-C bounded qualification artifact after independent review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUBRIC_SCHEMA_VERSION = "rq1c-bounded-holdout-rubric-v1"
RUNTIME_SCHEMA_VERSION = "rq1c-bounded-qualification-runtime-v1"
REVIEW_SCHEMA_VERSION = "rq1c-bounded-independent-review-v1"
PROTOCOL_SCHEMA_VERSION = "rq1c-bounded-protocol-probes-v1"
REPORT_SCHEMA_VERSION = "rq1c-bounded-qualification-report-v1"
ANSWER_AUDIT_SCHEMA_VERSION = "answer-validation-audit-v1"
DEFAULT_RUBRIC = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "research_quality"
    / "rq1c_bounded_holdout_rubric.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "research_quality" / "RQ1C_BOUNDED_QUALIFICATION_REPORT.json"
)
_REQUIRED_PROBES = {
    "provider_timeout_retry",
    "user_cancellation",
    "provider_http_429",
    "provider_http_503",
    "unreadable_page",
    "duplicate_republication",
}
_REQUIRED_ANSWER_PHASES = {"answer_generation", "answer_claim_binding"}
_ANSWER_PHASE_OUTCOMES = {
    "completed",
    "passed",
    "rejected",
    "budget_exhausted",
    "interrupted",
}
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _case_ids(records: Any, *, key: str = "case_id") -> list[str]:
    if not isinstance(records, list):
        raise ValueError("cases must be a list")
    ids: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("case must be an object")
        case_id = str(record.get(key) or "")
        if not case_id or case_id in ids:
            raise ValueError("invalid or duplicate case id")
        ids.append(case_id)
    return ids


def _require_git_sha(value: Any, label: str) -> str:
    git_sha = str(value or "").strip().lower()
    if not _HEX40.fullmatch(git_sha):
        raise ValueError(f"{label} must be an exact 40-character git sha")
    return git_sha


def _validate_rubric(rubric: dict[str, Any]) -> tuple[set[str], dict[str, int]]:
    if rubric.get("schema_version") != RUBRIC_SCHEMA_VERSION:
        raise ValueError("unsupported RQ1-C rubric schema")
    ids = set(_case_ids(rubric.get("cases"), key="id"))
    if len(ids) != 12:
        raise ValueError("RQ1-C rubric must define exactly 12 cases")
    gate = rubric.get("gate")
    if not isinstance(gate, dict):
        raise ValueError("RQ1-C rubric gate missing")
    frozen = {
        "truthfulness_required": 12,
        "quality_required": 10,
        "hard_failures_allowed": 0,
        "max_candidates": 20,
        "max_reads": 8,
        "max_model_calls": 6,
        "soft_timeout_seconds": 45,
        "hard_timeout_seconds": 60,
    }
    for key, expected in frozen.items():
        if int(gate.get(key, -1)) != expected:
            raise ValueError(f"RQ1-C rubric changed frozen gate: {key}")
    return ids, frozen


def _bounded_nonnegative(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _answer_validation_is_reviewable(
    answer: Mapping[str, Any], expected_answer_sha: str
) -> bool:
    validation = answer.get("validation")
    if not isinstance(validation, Mapping):
        return False
    if validation.get("schema_version") != ANSWER_AUDIT_SCHEMA_VERSION:
        return False
    candidate_sha = str(validation.get("candidate_answer_sha256") or "").strip().lower()
    learner_sha = str(validation.get("learner_answer_sha256") or "").strip().lower()
    if not _HEX64.fullmatch(candidate_sha):
        raise ValueError("production answer audit candidate sha256 invalid")
    if not _HEX64.fullmatch(learner_sha):
        raise ValueError("production answer audit learner sha256 invalid")
    if learner_sha != expected_answer_sha:
        raise ValueError("production answer audit learner sha256 mismatch")
    phases = validation.get("phases")
    if not isinstance(phases, Mapping):
        return False
    if not _REQUIRED_ANSWER_PHASES.issubset(phases):
        return False
    for phase_name in _REQUIRED_ANSWER_PHASES:
        detail = phases.get(phase_name)
        if not isinstance(detail, Mapping):
            return False
        if detail.get("attempted") is not True:
            return False
        model_calls = _bounded_nonnegative(detail.get("model_calls"))
        attempts = _bounded_nonnegative(detail.get("attempts"))
        if model_calls is None or attempts is None or attempts > model_calls:
            raise ValueError(f"invalid production answer phase counts: {phase_name}")
        if str(detail.get("outcome") or "") not in _ANSWER_PHASE_OUTCOMES:
            return False
    generation = phases.get("answer_generation")
    if not isinstance(generation, Mapping):
        return False
    generation_calls = _bounded_nonnegative(generation.get("model_calls"))
    return generation_calls is not None and generation_calls >= 1


def _answer_surface_is_reviewable(record: Mapping[str, Any]) -> bool:
    answer = record.get("answer")
    if not isinstance(answer, Mapping):
        return False
    status = str(answer.get("status") or "").strip()
    if status != "available":
        return False
    if str(answer.get("source") or "").strip() != "production_chat":
        return False
    if str(answer.get("turn_id") or "").strip() == "":
        return False
    if str(answer.get("turn_status") or "").strip() != "completed":
        return False
    text = str(answer.get("text") or "")
    if not text.strip():
        return False
    supplied_hash = str(answer.get("content_sha256") or "").strip().lower()
    if not _HEX64.fullmatch(supplied_hash):
        raise ValueError("reviewable final answer must include exact content sha256")
    expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if supplied_hash != expected_hash:
        raise ValueError("reviewable final answer content sha256 mismatch")
    return _answer_validation_is_reviewable(answer, expected_hash)


def _runtime_budget_is_valid(record: Mapping[str, Any], gate: Mapping[str, int]) -> bool:
    observed = record.get("budget_observed")
    if not isinstance(observed, Mapping):
        return False
    candidates = _bounded_nonnegative(observed.get("candidate_count"))
    reads = _bounded_nonnegative(observed.get("read_count"))
    model_calls = _bounded_nonnegative(observed.get("model_call_count"))
    elapsed = observed.get("elapsed_seconds")
    try:
        elapsed_seconds = float(elapsed)
    except (TypeError, ValueError):
        return False
    if candidates is None or reads is None or model_calls is None or elapsed_seconds < 0:
        return False
    return (
        candidates <= gate["max_candidates"]
        and reads <= gate["max_reads"]
        and model_calls <= gate["max_model_calls"]
        and elapsed_seconds <= gate["hard_timeout_seconds"]
    )


def _validate_runtime(
    runtime: dict[str, Any], rubric_ids: set[str], gate: Mapping[str, int]
) -> tuple[int, int, int, str]:
    if runtime.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError("unsupported RQ1-C runtime artifact schema")
    git_sha = _require_git_sha(runtime.get("git_sha"), "runtime artifact git_sha")
    leakage = runtime.get("leakage_contract")
    if not isinstance(leakage, dict):
        raise ValueError("runtime artifact missing leakage contract")
    if leakage.get("rubric_loaded_by_runner") is not False:
        raise ValueError("runtime runner loaded evaluation rubric")
    if leakage.get("stores_research_query_text") is not False:
        raise ValueError("runtime artifact may not store research query text")
    if leakage.get("captures_production_final_answer") is not True:
        raise ValueError("runtime runner did not capture production final answers")
    if leakage.get("second_web_acquisition_during_synthesis") is not False:
        raise ValueError("runtime synthesis started an unbudgeted second web acquisition")
    records = runtime.get("cases")
    runtime_ids = set(_case_ids(records))
    if runtime_ids != rubric_ids:
        raise ValueError("runtime/rubric case ids differ")
    runner_errors = 0
    budget_violations = 0
    reviewable_answers = 0
    for record in records:
        if record.get("runner_error_type"):
            runner_errors += 1
        violations = record.get("budget_contract_violations")
        marker_violation = isinstance(violations, list) and bool(violations)
        if marker_violation or not _runtime_budget_is_valid(record, gate):
            budget_violations += 1
        reviewable_answers += int(_answer_surface_is_reviewable(record))
        for audit in ((record.get("search") or {}).get("audits") or []):
            if not isinstance(audit, dict):
                continue
            if "query" in audit or "query_text" in audit:
                raise ValueError("runtime artifact leaked generated research query text")
            digest = str(audit.get("query_sha256") or "")
            if digest and not _HEX64.fullmatch(digest):
                raise ValueError("invalid research query sha256")
    return runner_errors, budget_violations, reviewable_answers, git_sha


def _validate_review(
    review: dict[str, Any], runtime_path: Path, ids: set[str]
) -> tuple[int, int, int]:
    if review.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported RQ1-C independent review schema")
    expected_sha = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    if review.get("runtime_artifact_sha256") != expected_sha:
        raise ValueError("independent review is not bound to this runtime artifact")
    records = review.get("cases")
    review_ids = set(_case_ids(records))
    if review_ids != ids:
        raise ValueError("review/runtime case ids differ")
    truthful = 0
    quality = 0
    hard_failures = 0
    for record in records:
        truth = record.get("truthfulness")
        quality_value = record.get("quality")
        failures = record.get("hard_failures")
        if truth not in {"pass", "fail"} or quality_value not in {"pass", "fail"}:
            raise ValueError("review verdicts must be pass/fail")
        if not isinstance(failures, list):
            raise ValueError("review hard_failures must be a list")
        truthful += int(truth == "pass")
        quality += int(quality_value == "pass")
        hard_failures += len(failures)
    return truthful, quality, hard_failures


def _validate_protocol(
    protocol: dict[str, Any], runtime_path: Path, runtime_git_sha: str
) -> tuple[int, list[str]]:
    if protocol.get("schema_version") != PROTOCOL_SCHEMA_VERSION:
        raise ValueError("unsupported RQ1-C protocol probe schema")
    expected_runtime_sha = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    if protocol.get("runtime_artifact_sha256") != expected_runtime_sha:
        raise ValueError("protocol probes are not bound to this runtime artifact")
    protocol_git_sha = _require_git_sha(
        protocol.get("git_sha"), "protocol artifact git_sha"
    )
    if protocol_git_sha != runtime_git_sha:
        raise ValueError("protocol/runtime git sha mismatch")
    leakage = protocol.get("leakage_contract")
    if not isinstance(leakage, dict):
        raise ValueError("protocol artifact missing leakage contract")
    for key in (
        "stores_generated_query_text",
        "stores_page_bodies",
        "stores_raw_provider_errors",
    ):
        if leakage.get(key) is not False:
            raise ValueError(f"protocol artifact violates leakage contract: {key}")
    records = protocol.get("probes")
    if not isinstance(records, list):
        raise ValueError("protocol probes must be a list")
    seen: set[str] = set()
    failed: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("protocol probe must be an object")
        probe_id = str(record.get("id") or "")
        if probe_id in seen or probe_id not in _REQUIRED_PROBES:
            raise ValueError(f"invalid or duplicate protocol probe: {probe_id}")
        seen.add(probe_id)
        if record.get("status") not in {"pass", "fail"}:
            raise ValueError("protocol probe status must be pass/fail")
        if record.get("status") != "pass":
            failed.append(probe_id)
    missing = sorted(_REQUIRED_PROBES - seen)
    if missing:
        raise ValueError(f"missing protocol probes: {missing}")
    return len(seen), failed


def evaluate(
    *,
    runtime_path: Path,
    rubric_path: Path,
    review_path: Path,
    protocol_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    runtime = _load_json(runtime_path)
    rubric = _load_json(rubric_path)
    review = _load_json(review_path)
    protocol = _load_json(protocol_path)
    ids, gate = _validate_rubric(rubric)
    (
        runner_errors,
        budget_violations,
        reviewable_answers,
        runtime_git_sha,
    ) = _validate_runtime(runtime, ids, gate)
    truthful, quality, hard_failures = _validate_review(review, runtime_path, ids)
    probe_count, failed_probes = _validate_protocol(
        protocol, runtime_path, runtime_git_sha
    )
    checks = {
        "answer_surface": reviewable_answers == len(ids),
        "truthfulness": truthful == gate["truthfulness_required"],
        "quality": quality >= gate["quality_required"],
        "hard_failures": hard_failures == gate["hard_failures_allowed"],
        "runner_errors": runner_errors == 0,
        "runtime_budget": budget_violations == 0,
        "protocol_probes": not failed_probes and probe_count == len(_REQUIRED_PROBES),
    }
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "inputs": {
            "git_sha": runtime_git_sha,
            "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            "rubric_sha256": hashlib.sha256(rubric_path.read_bytes()).hexdigest(),
            "review_sha256": hashlib.sha256(review_path.read_bytes()).hexdigest(),
            "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        },
        "scores": {
            "reviewable_answer_cases": f"{reviewable_answers}/12",
            "truthfulness": f"{truthful}/12",
            "quality": f"{quality}/12",
            "hard_failures": hard_failures,
            "runner_error_cases": runner_errors,
            "budget_violation_cases": budget_violations,
            "failed_protocol_probes": failed_probes,
        },
        "checks": checks,
        "decision": "GO" if all(checks.values()) else "NO-GO",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rubric", type=Path, default=DEFAULT_RUBRIC)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report = evaluate(
        runtime_path=args.runtime.resolve(),
        rubric_path=args.rubric.resolve(),
        review_path=args.review.resolve(),
        protocol_path=args.protocol.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
