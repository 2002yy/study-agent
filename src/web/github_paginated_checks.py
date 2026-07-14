"""Paginated GitHub checks, workflow runs, and workflow jobs."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.web.github_paginated_base import (
    PaginatedGitHubBase,
    collection_partial,
    dict_errors,
)
from src.web.github_provider_pagination import GitHubProviderRequestBudget
from src.web.github_work_items import GitHubWorkItemBudget


class PaginatedGitHubChecksService(PaginatedGitHubBase):
    """Add commit-pinned check, workflow-run, and job collection reads."""

    def _checks_for_commit(
        self,
        repo_url: str,
        *,
        requested_ref: str,
        commit_sha: str,
        tree_sha: str = "",
        max_runs: int,
        max_checks: int,
        max_jobs: int,
        include_jobs: bool,
        request_budget: GitHubProviderRequestBudget,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}

        check_pages = self._rest_collection(
            operation=f"check_runs:{target.repository}",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/commits/{quote(commit_sha, safe='')}/check-runs"
            ),
            limit=max_checks,
            request_budget=request_budget,
            key="check_runs",
        )
        run_pages = self._rest_collection(
            operation=f"workflow_runs:{target.repository}",
            path=f"/repos/{quote(target.owner)}/{quote(target.repo)}/actions/runs",
            limit=max_runs,
            request_budget=request_budget,
            key="workflow_runs",
            params={"head_sha": commit_sha},
        )
        checks = [self._check_run(item) for item in check_pages["items"]]
        runs = [self._workflow_run(item) for item in run_pages["items"]]
        provider_errors = [
            *dict_errors(check_pages.get("errors")),
            *dict_errors(run_pages.get("errors")),
        ]

        jobs: list[dict[str, Any]] = []
        job_pagination: list[dict[str, Any]] = []
        jobs_truncated = False
        if include_jobs:
            remaining = max_jobs
            for run in runs:
                if remaining <= 0:
                    jobs_truncated = True
                    break
                run_id = int(run.get("id") or 0)
                if run_id <= 0:
                    continue
                pages = self._rest_collection(
                    operation=f"workflow_jobs:{target.repository}:{run_id}",
                    path=(
                        f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                        f"/actions/runs/{run_id}/jobs"
                    ),
                    limit=remaining,
                    request_budget=request_budget,
                    key="jobs",
                )
                converted = [self._job(item) for item in pages["items"]]
                jobs.extend(converted)
                remaining = max_jobs - len(jobs)
                provider_errors.extend(dict_errors(pages.get("errors")))
                job_pagination.append(
                    {
                        "run_id": run_id,
                        "pages_fetched": pages["pages_fetched"],
                        "provider_count": pages["provider_count"],
                        "returned_count": len(converted),
                        "truncated": pages["truncated"],
                        "stop_reason": pages["stop_reason"],
                    }
                )
                jobs_truncated = jobs_truncated or bool(pages["truncated"])
                if request_budget.exhausted_operations:
                    jobs_truncated = True
                    break

        no_check_evidence = check_pages["pages_fetched"] == 0
        no_run_evidence = run_pages["pages_fetched"] == 0
        if no_check_evidence and no_run_evidence:
            return {
                "ok": False,
                "status": "unavailable",
                "repository": target.repository,
                "requested_ref": requested_ref,
                "commit_sha": commit_sha,
                "error": "github_checks_providers_unavailable",
                "provider_errors": provider_errors,
                "pagination": {
                    "check_runs": check_pages,
                    "workflow_runs": run_pages,
                    "workflow_jobs": job_pagination,
                },
                "provider_request_budget": request_budget.to_dict(),
            }

        partial = (
            bool(provider_errors)
            or collection_partial(check_pages)
            or collection_partial(run_pages)
            or any(
                str(item.get("stop_reason") or "")
                in {
                    "provider_error",
                    "request_budget_exhausted",
                    "page_budget_exhausted",
                }
                for item in job_pagination
            )
        )
        return {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if partial else "complete",
            "repository": target.repository,
            "evidence_repository": target.repository,
            "requested_ref": requested_ref,
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "check_runs": checks,
            "check_count": len(checks),
            "provider_check_count": int(check_pages["provider_count"]),
            "workflow_runs": runs,
            "workflow_run_count": len(runs),
            "provider_workflow_run_count": int(run_pages["provider_count"]),
            "jobs": jobs,
            "job_count": len(jobs),
            "provider_errors": provider_errors,
            "truncated": (
                bool(check_pages["truncated"])
                or bool(run_pages["truncated"])
                or jobs_truncated
            ),
            "pagination": {
                "check_runs": {
                    key: check_pages[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                },
                "workflow_runs": {
                    key: run_pages[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                },
                "workflow_jobs": job_pagination,
            },
            "budget": {
                "max_runs": max_runs,
                "max_checks": max_checks,
                "max_jobs": max_jobs,
                "include_jobs": include_jobs,
            },
            "provider_request_budget": request_budget.to_dict(),
        }

    def checks(
        self,
        repo_url: str,
        *,
        ref: str = "",
        max_runs: int | None = None,
        max_checks: int | None = None,
        max_jobs: int | None = None,
        include_jobs: bool = True,
        max_provider_requests: int | None = None,
        max_pages_per_collection: int | None = None,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        resolved = self.history_service.resolve_ref(repo_url, ref)
        if resolved.get("ok") is not True:
            return resolved
        item_budget = GitHubWorkItemBudget.from_env()
        run_limit = max(1, min(int(max_runs or item_budget.max_runs), 100))
        check_limit = max(1, min(int(max_checks or item_budget.max_checks), 100))
        job_limit = max(1, min(int(max_jobs or item_budget.max_jobs), 300))
        request_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        commit_sha = str(resolved.get("commit_sha") or "")
        cache_key = (
            f"checks-v2:{target.repository}:{commit_sha}:{run_limit}:{check_limit}:"
            f"{job_limit}:{int(include_jobs)}:{request_budget.max_requests}:"
            f"{request_budget.max_pages_per_collection}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        result = self._checks_for_commit(
            repo_url,
            requested_ref=str(resolved.get("requested_ref") or ""),
            commit_sha=commit_sha,
            tree_sha=str(resolved.get("tree_sha") or ""),
            max_runs=run_limit,
            max_checks=check_limit,
            max_jobs=job_limit,
            include_jobs=include_jobs,
            request_budget=request_budget,
        )
        return self._cache_put(cache_key, result)
