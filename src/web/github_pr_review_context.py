"""Source-backed pull-request review-context orchestration."""

from __future__ import annotations

from typing import Any

from src.web.github_change_impact import GitHubChangeImpactService
from src.web.github_pr_ci_association import associate_failed_ci
from src.web.github_pr_review_mapping import (
    changed_paths,
    dict_items,
    map_review_item,
    path_aliases,
    review_context_id,
    review_items,
    safe_int,
    symbol_records,
)
from src.web.github_work_items import GitHubWorkItemService


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
            for item in dict_items(impact.get("uncertainties"))
        )

        mapped_reviews = [
            map_review_item(
                item,
                symbols=symbol_records(impact),
                aliases=path_aliases(impact),
                paths=changed_paths(impact),
            )
            for item in review_items(pull)
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
        failed_checks, ci_associations, ci_uncertainties = associate_failed_ci(
            pull, impact
        )
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
        changed_file_count = max(0, safe_int(pull.get("changed_files")))
        impact_file_count = len(dict_items(impact.get("file_changes")))
        impact_ratio = (
            min(1.0, impact_file_count / changed_file_count)
            if changed_file_count
            else (1.0 if impact.get("ok") is True else 0.0)
        )
        review_ratio = mapped_review_count / review_total if review_total else 1.0
        ci_ratio = associated_failed_jobs / failed_job_count if failed_job_count else 1.0
        immutable_ratio = 1.0
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
            "review_context_id": review_context_id(
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
            "affected_tests": dict_items(impact.get("tests")),
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
                "symbol_change_count": safe_int(
                    dict(impact.get("summary") or {}).get("symbol_change_count")
                ),
                "review_item_count": review_total,
                "mapped_review_item_count": mapped_review_count,
                "unresolved_review_thread_count": len(unresolved),
                "mapped_unresolved_review_thread_count": unresolved_mapped,
                "failed_check_count": len(failed_checks),
                "failed_job_count": failed_job_count,
                "associated_failed_job_count": associated_failed_jobs,
                "affected_test_count": len(dict_items(impact.get("tests"))),
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
