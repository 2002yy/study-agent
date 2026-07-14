"""Conservative failed-CI association for pull-request review context."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from src.web.github_pr_review_mapping import dict_items, safe_int, symbol_records

_FAILED_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "stale",
    "timed_out",
}
_TEST_TOKENS = {
    "test",
    "tests",
    "testing",
    "pytest",
    "vitest",
    "jest",
    "unittest",
    "integration",
    "e2e",
}
_TOKEN_STOPWORDS = {
    "action",
    "actions",
    "build",
    "check",
    "checks",
    "ci",
    "job",
    "lint",
    "run",
    "step",
    "test",
    "tests",
    "testing",
    "unit",
    "workflow",
}
_WORD = re.compile(r"[A-Za-z0-9]+")


def _failed(value: Any) -> bool:
    return str(value or "").casefold() in _FAILED_CONCLUSIONS


def _tokens(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return {item.casefold() for item in _WORD.findall(expanded) if len(item) >= 2}


def _path_tokens(path: str) -> set[str]:
    source = PurePosixPath(str(path or ""))
    values = _tokens(str(source)) | _tokens(source.stem)
    return {item for item in values if item not in _TOKEN_STOPWORDS}


def _specific_matches(text: str, paths: Iterable[str]) -> list[str]:
    lowered = str(text or "").casefold()
    context_tokens = _tokens(text) - _TOKEN_STOPWORDS
    matches: list[str] = []
    for path in paths:
        normalized = str(path or "").casefold()
        name = PurePosixPath(path).name.casefold()
        stem = PurePosixPath(path).stem.casefold()
        tokens = _path_tokens(path)
        if normalized and normalized in lowered:
            matches.append(path)
        elif name and name in lowered:
            matches.append(path)
        elif len(stem) >= 4 and stem in lowered:
            matches.append(path)
        elif len(tokens & context_tokens) >= 2:
            matches.append(path)
    return sorted(set(matches))


def associate_failed_ci(
    pull: dict[str, Any], impact: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    checks = dict(pull.get("checks")) if isinstance(pull.get("checks"), dict) else {}
    failed_checks = [
        {
            "id": safe_int(item.get("id")),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "conclusion": str(item.get("conclusion") or ""),
            "details_url": str(item.get("details_url") or ""),
        }
        for item in dict_items(checks.get("check_runs"))
        if _failed(item.get("conclusion"))
    ]
    failed_jobs = [
        item for item in dict_items(checks.get("jobs")) if _failed(item.get("conclusion"))
    ]
    test_paths = [
        str(item.get("path") or "") for item in dict_items(impact.get("tests"))
    ]
    affected_paths = [
        str(item.get("path") or "")
        for item in dict_items(impact.get("affected_files"))
    ]
    symbols = symbol_records(impact)
    associations: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    for job in failed_jobs:
        failed_steps = [
            step
            for step in dict_items(job.get("steps"))
            if _failed(step.get("conclusion"))
        ]
        context = " ".join(
            [
                str(job.get("name") or ""),
                *(str(step.get("name") or "") for step in failed_steps),
            ]
        )
        matched_tests = _specific_matches(context, test_paths)
        matched_files = _specific_matches(context, affected_paths)
        context_tokens = _tokens(context)
        matched_symbols = sorted(
            {
                str(symbol.get("qualified_name") or symbol.get("name") or "")
                for symbol in symbols
                if (
                    _tokens(
                        str(symbol.get("qualified_name") or symbol.get("name") or "")
                    )
                    - _TOKEN_STOPWORDS
                )
                & (context_tokens - _TOKEN_STOPWORDS)
            }
            - {""}
        )
        reasons: list[str] = []
        confidence = "low"
        if matched_tests or matched_files or matched_symbols:
            reasons.append("specific_name_or_token_match")
            confidence = "high" if matched_tests or matched_symbols else "medium"
        elif context_tokens & _TEST_TOKENS and test_paths:
            matched_tests = sorted(set(test_paths))[:50]
            reasons.append("generic_test_job_matches_affected_tests_only")
        else:
            uncertainties.append(
                {
                    "kind": "failed_ci_job_unmapped",
                    "job_id": safe_int(job.get("id")),
                    "job_name": str(job.get("name") or ""),
                }
            )
        associations.append(
            {
                "job": {
                    "id": safe_int(job.get("id")),
                    "run_id": safe_int(job.get("run_id")),
                    "name": str(job.get("name") or ""),
                    "status": str(job.get("status") or ""),
                    "conclusion": str(job.get("conclusion") or ""),
                    "url": str(job.get("url") or ""),
                },
                "failed_steps": [
                    {
                        "name": str(step.get("name") or ""),
                        "number": safe_int(step.get("number")),
                        "conclusion": str(step.get("conclusion") or ""),
                    }
                    for step in failed_steps
                ],
                "association": {
                    "status": (
                        "associated"
                        if matched_tests or matched_files or matched_symbols
                        else "unmapped"
                    ),
                    "confidence": confidence,
                    "reasons": reasons,
                    "tests": matched_tests,
                    "files": matched_files,
                    "symbols": matched_symbols,
                },
            }
        )
    if failed_checks and not failed_jobs:
        uncertainties.append(
            {
                "kind": "failed_checks_without_failed_job_evidence",
                "check_count": len(failed_checks),
            }
        )
    return failed_checks, associations, uncertainties
