"""Persistent cache wrapper for paginated GitHub work-item providers."""

from __future__ import annotations

from typing import Any

from src.repositories.github_research_cache_repository import (
    GitHubResearchCacheRepository,
)
from src.web.github_cache_policy import GitHubResearchCachePolicy
from src.web.github_paginated_work_items import PaginatedGitHubWorkItemService
from src.web.github_provider_pagination import GitHubProviderRequestBudget
from src.web.github_reader import parse_github_url
from src.web.github_work_items import GitHubWorkItemBudget


class PersistentGitHubWorkItemService(PaginatedGitHubWorkItemService):
    """Add restart-safe SQLite reuse without changing provider semantics."""

    def __init__(
        self,
        *args: Any,
        cache_repository: GitHubResearchCacheRepository,
        cache_policy: GitHubResearchCachePolicy | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.cache_repository = cache_repository
        self.cache_policy = cache_policy or GitHubResearchCachePolicy.from_env()

    def _persistent_get(
        self,
        cache_kind: str,
        identity: dict[str, Any],
    ) -> dict[str, Any] | None:
        entry = self.cache_repository.get(
            cache_kind,
            identity,
            schema_version=self.cache_policy.schema_version,
            allow_partial=self.cache_policy.reuse_partial,
        )
        if entry is None:
            return None
        return {
            **entry.payload,
            "cache_hit": True,
            "cache_source": "sqlite",
            "cache_status": entry.cache_status,
        }

    def _persistent_put(
        self,
        cache_kind: str,
        repository: str,
        identity: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        ttl = self.cache_policy.ttl_for(result, cache_kind=cache_kind)
        if ttl > 0:
            self.cache_repository.put(
                cache_kind,
                repository,
                identity,
                result,
                ttl_seconds=ttl,
                schema_version=self.cache_policy.schema_version,
            )
        return result

    @staticmethod
    def _repository(repo_url: str) -> str:
        target = parse_github_url(repo_url)
        return target.repository if target is not None else str(repo_url or "")

    def pull_request(
        self,
        repo_url: str,
        number: int,
        *,
        max_files: int | None = None,
        max_patch_chars: int | None = None,
        max_comments: int | None = None,
        max_reviews: int | None = None,
        include_checks: bool = True,
        max_provider_requests: int | None = None,
        max_pages_per_collection: int | None = None,
    ) -> dict[str, Any]:
        item_budget = GitHubWorkItemBudget.from_env()
        provider_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        identity = {
            "repository": self._repository(repo_url),
            "number": int(number),
            "max_files": max(1, min(int(max_files or item_budget.max_files), 100)),
            "max_patch_chars": max(
                1_000,
                min(
                    int(max_patch_chars or item_budget.max_patch_chars),
                    1_000_000,
                ),
            ),
            "max_comments": max(
                1,
                min(int(max_comments or item_budget.max_comments), 100),
            ),
            "max_reviews": max(
                1,
                min(int(max_reviews or item_budget.max_reviews), 100),
            ),
            "include_checks": bool(include_checks),
            "max_provider_requests": provider_budget.max_requests,
            "max_pages_per_collection": provider_budget.max_pages_per_collection,
        }
        cached = self._persistent_get("pull_request", identity)
        if cached is not None:
            return cached
        result = super().pull_request(
            repo_url,
            number,
            max_files=identity["max_files"],
            max_patch_chars=identity["max_patch_chars"],
            max_comments=identity["max_comments"],
            max_reviews=identity["max_reviews"],
            include_checks=include_checks,
            max_provider_requests=provider_budget.max_requests,
            max_pages_per_collection=provider_budget.max_pages_per_collection,
        )
        return self._persistent_put(
            "pull_request",
            identity["repository"],
            identity,
            result,
        )

    def issue(
        self,
        repo_url: str,
        number: int,
        *,
        max_comments: int | None = None,
        max_events: int | None = None,
        max_provider_requests: int | None = None,
        max_pages_per_collection: int | None = None,
    ) -> dict[str, Any]:
        item_budget = GitHubWorkItemBudget.from_env()
        provider_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        identity = {
            "repository": self._repository(repo_url),
            "number": int(number),
            "max_comments": max(
                1,
                min(int(max_comments or item_budget.max_comments), 100),
            ),
            "max_events": max(
                1,
                min(int(max_events or item_budget.max_events), 100),
            ),
            "max_provider_requests": provider_budget.max_requests,
            "max_pages_per_collection": provider_budget.max_pages_per_collection,
        }
        cached = self._persistent_get("issue", identity)
        if cached is not None:
            return cached
        result = super().issue(
            repo_url,
            number,
            max_comments=identity["max_comments"],
            max_events=identity["max_events"],
            max_provider_requests=provider_budget.max_requests,
            max_pages_per_collection=provider_budget.max_pages_per_collection,
        )
        return self._persistent_put(
            "issue",
            identity["repository"],
            identity,
            result,
        )

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
        resolved = self.history_service.resolve_ref(repo_url, ref)
        if resolved.get("ok") is not True:
            return resolved
        item_budget = GitHubWorkItemBudget.from_env()
        provider_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        commit_sha = str(resolved.get("commit_sha") or "")
        identity = {
            "repository": self._repository(repo_url),
            "commit_sha": commit_sha,
            "max_runs": max(1, min(int(max_runs or item_budget.max_runs), 100)),
            "max_checks": max(
                1,
                min(int(max_checks or item_budget.max_checks), 100),
            ),
            "max_jobs": max(1, min(int(max_jobs or item_budget.max_jobs), 300)),
            "include_jobs": bool(include_jobs),
            "max_provider_requests": provider_budget.max_requests,
            "max_pages_per_collection": provider_budget.max_pages_per_collection,
        }
        cached = self._persistent_get("checks", identity)
        if cached is not None:
            return {
                **cached,
                "requested_ref": str(resolved.get("requested_ref") or ref),
            }
        result = super().checks(
            repo_url,
            ref=commit_sha,
            max_runs=identity["max_runs"],
            max_checks=identity["max_checks"],
            max_jobs=identity["max_jobs"],
            include_jobs=include_jobs,
            max_provider_requests=provider_budget.max_requests,
            max_pages_per_collection=provider_budget.max_pages_per_collection,
        )
        result = {
            **result,
            "requested_ref": str(resolved.get("requested_ref") or ref),
            "resolved_ref": commit_sha,
        }
        return self._persistent_put(
            "checks",
            identity["repository"],
            identity,
            result,
        )

    def ci_logs(
        self,
        repo_url: str,
        job_id: int,
        *,
        max_chars: int | None = None,
        max_lines: int | None = None,
    ) -> dict[str, Any]:
        item_budget = GitHubWorkItemBudget.from_env()
        identity = {
            "repository": self._repository(repo_url),
            "job_id": int(job_id),
            "max_chars": max(
                1_000,
                min(int(max_chars or item_budget.max_log_chars), 200_000),
            ),
            "max_lines": max(
                20,
                min(int(max_lines or item_budget.max_log_lines), 2_000),
            ),
        }
        cached = self._persistent_get("ci_logs", identity)
        if cached is not None:
            return cached
        result = super().ci_logs(
            repo_url,
            job_id,
            max_chars=identity["max_chars"],
            max_lines=identity["max_lines"],
        )
        return self._persistent_put(
            "ci_logs",
            identity["repository"],
            identity,
            result,
        )
