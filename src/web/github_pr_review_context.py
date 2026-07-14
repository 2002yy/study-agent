"""Source-backed pull-request review context.

This module composes existing immutable PR, review, checks/jobs, and version-aware
change-impact evidence. It maps review locations and failed CI conservatively,
reports coverage and uncertainty, and intentionally does not issue a correctness
verdict.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any, Iterable

from src.web.github_change_impact import GitHubChangeImpactService
from src.web.github_work_items import GitHubWorkItemService

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


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_text(value: Any, limit: int = 1_000) -> str:
    text = " ".join(str(value or "").split())
    return text[: max(0, int(limit))]


def _tokens(value: str) -> set[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return {item.casefold() for item in _WORD.findall(expanded) if len(item) >= 2}


def _path_tokens(path: str) -> set[str]:
    source = PurePosixPath(str(path or ""))
    values = _tokens(str(source)) | _tokens(source.stem)
    return {item for item in values if item not in _TOKEN_STOPWORDS}


def _line_range(item: dict[str, Any]) -> tuple[int, int]:
    line = _safe_int(item.get("line")) or _safe_int(item.get("original_line"))
    start = _safe_int(item.get("start_line")) or line
    if start <= 0 and line <= 0:
        return 0, 0
    start = max(1, start or line)
    return start, max(start, line or start)


def _overlaps(start: int, end: int, target_start: int, target_end: int) -> bool:
    if min(start, end, target_start, target_end) <= 0:
        return False
    return start <= target_end and end >= target_start


def _review_context_id(repository: str, number: int, base_sha: str, head_sha: str) -> str:
    digest = hashlib.sha256(
        f"{repository}\x1f{number}\x1f{base_sha}\x1f{head_sha}".encode("utf-8")
    ).hexdigest()[:24]
    return f"pr_review_{digest}"


def _symbol_records(impact: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for change in _dicts(impact.get("changes")):
        for bucket, review_side in (("old", "LEFT"), ("new", "RIGHT")):
            for symbol in _dicts(change.get(bucket)):
                evidence = (
                    dict(symbol.get("evidence"))
                    if isinstance(symbol.get("evidence"), dict)
                    else {}
                )
                start = max(1, _safe_int(evidence.get("start_line"), 1))
                end = max(start, _safe_int(evidence.get("end_line"), start))
                result.append(
                    {
                        "change_id": str(change.get("id") or ""),
                        "change_type": str(change.get("type") or ""),
                        "signature_changed": bool(change.get("signature_changed")),
                        "review_side": review_side,
                        "path": str(evidence.get("path") or ""),
                        "start_line": start,
                        "end_line": end,
                        "name": str(symbol.get("name") or ""),
                        "qualified_name": str(
                            symbol.get("qualified_name") or symbol.get("name") or ""
                        ),
                        "kind": str(symbol.get("kind") or ""),
                        "language": str(symbol.get("language") or ""),
                        "identity": dict(symbol.get("identity") or {}),
                        "evidence": evidence,
                    }
                )
    return result


def _path_aliases(impact: dict[str, Any]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = defaultdict(set)
    for item in _dicts(impact.get("file_changes")):
        old_path = str(item.get("old_path") or "")
        new_path = str(item.get("new_path") or "")
        if old_path and new_path and old_path != new_path:
            aliases[old_path].add(new_path)
            aliases[new_path].add(old_path)
    return aliases


def _review_items(pull: dict[str, Any]) -> list[dict[str, Any]]:
    review_threads = (
        dict(pull.get("review_threads"))
        if isinstance(pull.get("review_threads"), dict)
        else {}
    )
    threads = _dicts(review_threads.get("threads"))
    result: list[dict[str, Any]] = []
    covered_comment_ids: set[int] = set()
    for thread in threads:
        comments = _dicts(thread.get("comments"))
        covered_comment_ids.update(
            _safe_int(comment.get("id"))
            for comment in comments
            if _safe_int(comment.get("id")) > 0
        )
        result.append(
            {
                "kind": "review_thread",
                "id": str(thread.get("id") or ""),
                "path": str(thread.get("path") or ""),
                "line": _safe_int(thread.get("line")),
                "start_line": _safe_int(thread.get("start_line")),
                "side": str(thread.get("side") or ""),
                "is_resolved": bool(thread.get("is_resolved")),
                "is_outdated": bool(thread.get("is_outdated")),
                "comments": comments,
                "body": _bounded_text(comments[0].get("body") if comments else ""),
            }
        )
    for comment in _dicts(pull.get("inline_comments")):
        comment_id = _safe_int(comment.get("id"))
        if comment_id > 0 and comment_id in covered_comment_ids:
            continue
        result.append(
            {
                "kind": "inline_comment",
                "id": str(comment_id or comment.get("node_id") or ""),
                "path": str(comment.get("path") or ""),
                "line": _safe_int(comment.get("line"))
                or _safe_int(comment.get("original_line")),
                "start_line": _safe_int(comment.get("start_line")),
                "side": str(comment.get("side") or ""),
                "is_resolved": None,
                "is_outdated": False,
                "comments": [comment],
                "body": _bounded_text(comment.get("body")),
            }
        )
    return result


def _map_review_item(
    item: dict[str, Any],
    *,
    symbols: list[dict[str, Any]],
    aliases: dict[str, set[str]],
    changed_paths: set[str],
) -> dict[str, Any]:
    path = str(item.get("path") or "")
    side = str(item.get("side") or "").upper()
    start, end = _line_range(item)
    accepted_paths = {path, *aliases.get(path, set())} if path else set()
    candidates = [
        symbol
        for symbol in symbols
        if str(symbol.get("path") or "") in accepted_paths
        and (side not in {"LEFT", "RIGHT"} or symbol.get("review_side") == side)
        and (start <= 0 or _overlaps(start, end, symbol["start_line"], symbol["end_line"]))
    ]
    mapping: dict[str, Any]
    if candidates:
        smallest_span = min(
            _safe_int(candidate.get("end_line"))
            - _safe_int(candidate.get("start_line"))
            for candidate in candidates
        )
        narrowest = [
            candidate
            for candidate in candidates
            if _safe_int(candidate.get("end_line"))
            - _safe_int(candidate.get("start_line"))
            == smallest_span
        ]
        if len(narrowest) == 1:
            selected = narrowest[0]
            mapping = {
                "status": "mapped",
                "confidence": "high" if len(candidates) == 1 else "medium",
                "reason": (
                    "single_containing_symbol"
                    if len(candidates) == 1
                    else "unique_narrowest_containing_symbol"
                ),
                "change_id": selected["change_id"],
                "change_type": selected["change_type"],
                "signature_changed": selected["signature_changed"],
                "symbol": {
                    "name": selected["name"],
                    "qualified_name": selected["qualified_name"],
                    "kind": selected["kind"],
                    "language": selected["language"],
                    "identity": selected["identity"],
                    "evidence": selected["evidence"],
                },
            }
        else:
            mapping = {
                "status": "ambiguous",
                "confidence": "low",
                "reason": "multiple_symbols_share_review_location",
                "candidate_count": len(narrowest),
                "candidates": [
                    {
                        "change_id": candidate["change_id"],
                        "qualified_name": candidate["qualified_name"],
                        "kind": candidate["kind"],
                        "evidence": candidate["evidence"],
                    }
                    for candidate in narrowest[:10]
                ],
            }
    elif path and path in changed_paths:
        mapping = {
            "status": "file_only",
            "confidence": "low",
            "reason": "changed_file_found_but_no_unique_symbol",
            "path": path,
        }
    else:
        mapping = {
            "status": "unmapped",
            "confidence": "low",
            "reason": "review_location_not_in_change_impact",
            "path": path,
        }
    return {**item, "line_range": {"start_line": start, "end_line": end}, "mapping": mapping}


def _failed(value: Any) -> bool:
    return str(value or "").casefold() in _FAILED_CONCLUSIONS


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


def _ci_associations(
    pull: dict[str, Any], impact: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    checks = dict(pull.get("checks")) if isinstance(pull.get("checks"), dict) else {}
    failed_checks = [
        {
            "id": _safe_int(item.get("id")),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "conclusion": str(item.get("conclusion") or ""),
            "details_url": str(item.get("details_url") or ""),
        }
        for item in _dicts(checks.get("check_runs"))
        if _failed(item.get("conclusion"))
    ]
    failed_jobs = [item for item in _dicts(checks.get("jobs")) if _failed(item.get("conclusion"))]
    test_paths = [str(item.get("path") or "") for item in _dicts(impact.get("tests"))]
    affected_paths = [
        str(item.get("path") or "") for item in _dicts(impact.get("affected_files"))
    ]
    symbol_records = _symbol_records(impact)
    associations: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []
    for job in failed_jobs:
        failed_steps = [
            step for step in _dicts(job.get("steps")) if _failed(step.get("conclusion"))
        ]
        context = " ".join(
            [str(job.get("name") or ""), *(str(step.get("name") or "") for step in failed_steps)]
        )
        matched_tests = _specific_matches(context, test_paths)
        matched_files = _specific_matches(context, affected_paths)
        context_tokens = _tokens(context)
        matched_symbols = sorted(
            {
                str(symbol.get("qualified_name") or symbol.get("name") or "")
                for symbol in symbol_records
                if (
                    _tokens(str(symbol.get("qualified_name") or symbol.get("name") or ""))
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
            confidence = "low"
        else:
            uncertainties.append(
                {
                    "kind": "failed_ci_job_unmapped",
                    "job_id": _safe_int(job.get("id")),
                    "job_name": str(job.get("name") or ""),
                }
            )
        associations.append(
            {
                "job": {
                    "id": _safe_int(job.get("id")),
                    "run_id": _safe_int(job.get("run_id")),
                    "name": str(job.get("name") or ""),
                    "status": str(job.get("status") or ""),
                    "conclusion": str(job.get("conclusion") or ""),
                    "url": str(job.get("url") or ""),
                },
                "failed_steps": [
                    {
                        "name": str(step.get("name") or ""),
                        "number": _safe_int(step.get("number")),
                        "conclusion": str(step.get("conclusion") or ""),
                    }
                    for step in failed_steps
                ],
                "association": {
                    "status": "associated"
                    if matched_tests or matched_files or matched_symbols
                    else "unmapped",
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


class GitHubPRReviewContextService:
    """Compose bounded PR evidence without generating an approval verdict."""

    def __init__(
        self,
        work_item_service: GitHubWorkItemService,
        change_impact_service: GitHubChangeImpactService,
    ) -> None:
        self.work_item_service = work_item_service
        self.change_impact_service = change_impact_service

    def build(
        self,
        repo_url: str,
        number: int,
        *,
        max_files: int = 20,
        max_symbols: int = 100,
        max_comments: int = 100,
        max_reviews: int = 100,
        depth: int = 2,
        max_impact_files: int = 40,
        max_edges: int = 160,
    ) -> dict[str, Any]:
        pull = self.work_item_service.pull_request(
            repo_url,
            number,
            max_files=max_files,
            max_comments=max_comments,
            max_reviews=max_reviews,
            include_checks=True,
        )
        if pull.get("ok") is not True:
            return pull
        base = dict(pull.get("base")) if isinstance(pull.get("base"), dict) else {}
        head = dict(pull.get("head")) if isinstance(pull.get("head"), dict) else {}
        base_sha = str(base.get("commit_sha") or "")
        head_sha = str(head.get("commit_sha") or "")
        if not base_sha or not head_sha:
            return {
                "ok": False,
                "status": "unavailable",
                "repository": str(pull.get("repository") or ""),
                "number": int(number),
                "error": "pull_request_missing_immutable_refs",
                "pull_request": pull,
            }
        impact = self.change_impact_service.analyze(
            repo_url,
            base_sha,
            head_sha,
            max_files=max_files,
            max_symbols=max_symbols,
            depth=depth,
            max_impact_files=max_impact_files,
            max_edges=max_edges,
        )
        uncertainties: list[dict[str, Any]] = []
        if impact.get("ok") is not True:
            uncertainties.append(
                {
                    "kind": "change_impact_unavailable",
                    "status": str(impact.get("status") or ""),
                    "error": str(impact.get("error") or ""),
                }
            )
            impact = {
                "ok": False,
                "status": str(impact.get("status") or "unavailable"),
                "provider_status": "partial",
                "file_changes": [],
                "changes": [],
                "tests": [],
                "affected_files": [],
                "uncertainties": [],
                "summary": {},
            }
        uncertainties.extend(
            {"kind": "change_impact_uncertainty", "detail": item}
            for item in _dicts(impact.get("uncertainties"))
        )
        symbols = _symbol_records(impact)
        aliases = _path_aliases(impact)
        changed_paths = {
            path
            for item in _dicts(impact.get("file_changes"))
            for path in (str(item.get("old_path") or ""), str(item.get("new_path") or ""))
            if path
        }
        mapped_reviews = [
            _map_review_item(
                item,
                symbols=symbols,
                aliases=aliases,
                changed_paths=changed_paths,
            )
            for item in _review_items(pull)
        ]
        for item in mapped_reviews:
            mapping = dict(item.get("mapping") or {})
            if mapping.get("status") in {"ambiguous", "unmapped"}:
                uncertainties.append(
                    {
                        "kind": "review_location_" + str(mapping.get("status")),
                        "review_kind": str(item.get("kind") or ""),
                        "review_id": str(item.get("id") or ""),
                        "path": str(item.get("path") or ""),
                        "reason": str(mapping.get("reason") or ""),
                    }
                )
        review_threads = (
            dict(pull.get("review_threads"))
            if isinstance(pull.get("review_threads"), dict)
            else {}
        )
        if review_threads.get("status") not in {"resolved", "not_requested"}:
            uncertainties.append(
                {
                    "kind": "review_threads_unavailable",
                    "status": str(review_threads.get("status") or ""),
                    "error": str(review_threads.get("error") or ""),
                }
            )
        failed_checks, ci_associations, ci_uncertainties = _ci_associations(pull, impact)
        uncertainties.extend(ci_uncertainties)
        if bool(pull.get("truncated")):
            uncertainties.append({"kind": "pull_request_evidence_truncated"})
        if bool(impact.get("truncated")):
            uncertainties.append({"kind": "change_impact_evidence_truncated"})

        review_total = len(mapped_reviews)
        mapped_review_count = sum(
            dict(item.get("mapping") or {}).get("status") == "mapped"
            for item in mapped_reviews
        )
        unresolved = [
            item
            for item in mapped_reviews
            if item.get("kind") == "review_thread" and item.get("is_resolved") is False
        ]
        unresolved_mapped = sum(
            dict(item.get("mapping") or {}).get("status") == "mapped"
            for item in unresolved
        )
        failed_job_count = len(ci_associations)
        associated_failed_jobs = sum(
            dict(item.get("association") or {}).get("status") == "associated"
            for item in ci_associations
        )
        changed_file_count = max(0, _safe_int(pull.get("changed_files")))
        impact_file_count = len(_dicts(impact.get("file_changes")))
        impact_ratio = (
            min(1.0, impact_file_count / changed_file_count)
            if changed_file_count
            else (1.0 if impact.get("ok") is True else 0.0)
        )
        review_ratio = mapped_review_count / review_total if review_total else 1.0
        ci_ratio = associated_failed_jobs / failed_job_count if failed_job_count else 1.0
        immutable_ratio = 1.0 if base_sha and head_sha else 0.0
        coverage_score = round(
            (impact_ratio + review_ratio + ci_ratio + immutable_ratio) / 4,
            3,
        )
        provider_partial = (
            str(pull.get("provider_status") or "") == "partial"
            or str(impact.get("provider_status") or "") == "partial"
            or bool(uncertainties)
        )
        coverage_status = (
            "complete"
            if coverage_score == 1.0 and not provider_partial
            else ("partial" if coverage_score >= 0.5 else "limited")
        )
        repository = str(pull.get("repository") or "")
        return {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if provider_partial else "complete",
            "kind": "github_pr_review_context",
            "review_context_id": _review_context_id(
                repository, int(number), base_sha, head_sha
            ),
            "repository": repository,
            "number": int(number),
            "title": str(pull.get("title") or ""),
            "url": str(pull.get("url") or ""),
            "base": base,
            "head": head,
            "review_items": mapped_reviews,
            "unresolved_review_items": unresolved,
            "failed_checks": failed_checks,
            "ci_associations": ci_associations,
            "affected_tests": _dicts(impact.get("tests")),
            "missing_test_symbols": list(impact.get("missing_test_symbols") or []),
            "evidence_coverage": {
                "status": coverage_status,
                "score": coverage_score,
                "immutable_ref_coverage": immutable_ratio,
                "changed_file_impact_coverage": round(impact_ratio, 3),
                "review_location_symbol_coverage": round(review_ratio, 3),
                "failed_job_association_coverage": round(ci_ratio, 3),
                "unresolved_thread_symbol_coverage": round(
                    unresolved_mapped / len(unresolved) if unresolved else 1.0,
                    3,
                ),
            },
            "summary": {
                "changed_file_count": changed_file_count,
                "impact_file_count": impact_file_count,
                "symbol_change_count": _safe_int(
                    dict(impact.get("summary") or {}).get("symbol_change_count")
                ),
                "review_item_count": review_total,
                "mapped_review_item_count": mapped_review_count,
                "unresolved_review_thread_count": len(unresolved),
                "mapped_unresolved_review_thread_count": unresolved_mapped,
                "failed_check_count": len(failed_checks),
                "failed_job_count": failed_job_count,
                "associated_failed_job_count": associated_failed_jobs,
                "affected_test_count": len(_dicts(impact.get("tests"))),
                "uncertainty_count": len(uncertainties),
            },
            "uncertainties": uncertainties,
            "verdict": {
                "status": "not_generated",
                "reason": "review_context_is_evidence_not_a_correctness_verdict",
            },
            "source_evidence": {
                "pull_request": pull,
                "change_impact": impact,
            },
            "truncated": bool(pull.get("truncated")) or bool(impact.get("truncated")),
            "budget": {
                "max_files": max_files,
                "max_symbols": max_symbols,
                "max_comments": max_comments,
                "max_reviews": max_reviews,
                "depth": depth,
                "max_impact_files": max_impact_files,
                "max_edges": max_edges,
            },
        }
