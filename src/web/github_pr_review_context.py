"""Source-backed pull-request review-context orchestration."""

from __future__ import annotations

import os
from typing import Any

from src.repositories.provider_cache_repository import (
    PROVIDER_CACHE_SCHEMA_VERSION,
    ProviderCacheRepository,
    provider_cache_key,
)
from src.web.github_change_impact import GitHubChangeImpactService
from src.web.github_paginated_work_items import PaginatedGitHubWorkItemService
from src.web.github_pr_ci_association import associate_failed_ci
from src.web.github_pr_review_mapping import (
    as_dict,
    changed_paths,
    dict_items,
    hunk_records,
    map_review_item,
    path_aliases,
    review_context_id,
    review_items,
    safe_int,
    symbol_records,
)


class GitHubPRReviewContextService:
    """Compose bounded PR evidence without generating an approval verdict."""

    def __init__(
        self,
        work_item_service: PaginatedGitHubWorkItemService,
        change_impact_service: GitHubChangeImpactService,
        cache_repository: ProviderCacheRepository | None = None,
    ) -> None:
        self.work_item_service = work_item_service
        self.change_impact_service = change_impact_service
        self.cache_repository = cache_repository or getattr(
            work_item_service, "cache_repository", None
        )

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
        max_provider_requests: int = 24,
        max_pages_per_collection: int = 10,
    ) -> dict[str, Any]:
        pull = self.work_item_service.pull_request(
            repo_url,
            number,
            max_files=max_files,
            max_comments=max_comments,
            max_reviews=max_reviews,
            include_checks=True,
            max_provider_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        if pull.get("ok") is not True:
            return pull
        base = as_dict(pull.get("base"))
        head = as_dict(pull.get("head"))
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

        repository = str(pull.get("repository") or "")
        budget = {
            "max_files": max_files,
            "max_symbols": max_symbols,
            "max_comments": max_comments,
            "max_reviews": max_reviews,
            "depth": depth,
            "max_impact_files": max_impact_files,
            "max_edges": max_edges,
            "max_provider_requests": max_provider_requests,
            "max_pages_per_collection": max_pages_per_collection,
        }
        cache_key = provider_cache_key(
            kind="review-context",
            repository=repository,
            request={
                "number": int(number),
                "budget": budget,
                "pull_evidence": {
                    "files": pull.get("files") or [],
                    "reviews": pull.get("reviews") or [],
                    "review_threads": pull.get("review_threads") or {},
                    "checks": pull.get("checks") or {},
                    "provider_status": str(pull.get("provider_status") or ""),
                    "truncated": bool(pull.get("truncated")),
                },
            },
            immutable_refs={"base_sha": base_sha, "head_sha": head_sha},
        )
        if self.cache_repository is not None:
            cached = self.cache_repository.get(cache_key)
            if cached is not None:
                return {
                    **cached.payload,
                    "cache_hit": True,
                    "cache_mode": "persistent",
                    "cache_schema_version": cached.schema_version,
                }

        uncertainties: list[dict[str, Any]] = []
        cross_repository = bool(pull.get("cross_repository"))
        if cross_repository:
            impact: dict[str, Any] = {
                "ok": False,
                "status": "unsupported",
                "provider_status": "partial",
                "file_changes": [],
                "changes": [],
                "tests": [],
                "affected_files": [],
                "uncertainties": [],
                "summary": {},
            }
            uncertainties.append(
                {
                    "kind": "cross_repository_change_impact_not_supported",
                    "base_repository": str(base.get("repository") or ""),
                    "head_repository": str(head.get("repository") or ""),
                    "reason": (
                        "same-repository change impact cannot safely pin a fork head"
                    ),
                }
            )
        else:
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

        symbols = symbol_records(impact)
        hunks = hunk_records(pull)
        aliases = path_aliases(impact)
        paths = changed_paths(impact)
        mapped_reviews = [
            map_review_item(
                item,
                symbols=symbols,
                hunks=hunks,
                aliases=aliases,
                paths=paths,
            )
            for item in review_items(pull)
        ]
        for item in mapped_reviews:
            mapping = as_dict(item.get("mapping"))
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
            hunk_mapping = as_dict(item.get("hunk_mapping"))
            if hunk_mapping.get("status") in {"ambiguous", "unmapped"}:
                uncertainties.append(
                    {
                        "kind": "review_hunk_" + str(hunk_mapping.get("status")),
                        "review_kind": str(item.get("kind") or ""),
                        "review_id": str(item.get("id") or ""),
                        "path": str(item.get("path") or ""),
                        "reason": str(hunk_mapping.get("reason") or ""),
                    }
                )

        review_threads = as_dict(pull.get("review_threads"))
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
            as_dict(item.get("mapping")).get("status") == "mapped"
            for item in mapped_reviews
        )
        mapped_hunk_count = sum(
            as_dict(item.get("hunk_mapping")).get("status") == "mapped"
            for item in mapped_reviews
        )
        unresolved = [
            item
            for item in mapped_reviews
            if item.get("kind") == "review_thread" and item.get("is_resolved") is False
        ]
        unresolved_mapped = sum(
            as_dict(item.get("mapping")).get("status") == "mapped"
            for item in unresolved
        )
        failed_job_count = len(ci_associations)
        associated_failed_jobs = sum(
            as_dict(item.get("association")).get("status") == "associated"
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
        hunk_ratio = mapped_hunk_count / review_total if review_total else 1.0
        ci_ratio = associated_failed_jobs / failed_job_count if failed_job_count else 1.0
        immutable_ratio = 1.0
        coverage_score = round(
            (impact_ratio + review_ratio + hunk_ratio + ci_ratio + immutable_ratio) / 5,
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
        result = {
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
            "cross_repository": cross_repository,
            "review_items": mapped_reviews,
            "unresolved_review_items": unresolved,
            "review_submissions": dict_items(pull.get("reviews")),
            "failed_checks": failed_checks,
            "ci_associations": ci_associations,
            "affected_tests": dict_items(impact.get("tests")),
            "missing_test_symbols": list(impact.get("missing_test_symbols") or []),
            "evidence_coverage": {
                "status": coverage_status,
                "score": coverage_score,
                "immutable_ref_coverage": immutable_ratio,
                "changed_file_impact_coverage": round(impact_ratio, 3),
                "review_location_hunk_coverage": round(hunk_ratio, 3),
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
                    as_dict(impact.get("summary")).get("symbol_change_count")
                ),
                "review_submission_count": len(dict_items(pull.get("reviews"))),
                "review_item_count": review_total,
                "mapped_review_hunk_count": mapped_hunk_count,
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
            "budget": budget,
            "provider_request_budget": as_dict(
                pull.get("provider_request_budget")
            ),
        }
        provider_status = str(result["provider_status"])
        if self.cache_repository is not None:
            self.cache_repository.put(
                cache_key=cache_key,
                kind="review-context",
                repository=repository,
                payload=result,
                immutable_refs={"base_sha": base_sha, "head_sha": head_sha},
                provider_status=provider_status,
                budget=budget,
                reuse_class="partial" if provider_status == "partial" else "complete",
                ttl_seconds=_cache_ttl_seconds(),
            )
        return {
            **result,
            "cache_hit": False,
            "cache_schema_version": PROVIDER_CACHE_SCHEMA_VERSION,
        }


def _cache_ttl_seconds() -> int:
    try:
        value = int(os.getenv("GITHUB_PROVIDER_CACHE_TTL_SECONDS", "300"))
    except (TypeError, ValueError):
        value = 300
    return max(0, min(value, 86_400))
