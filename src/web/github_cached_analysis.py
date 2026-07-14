"""Persistent cache wrappers for GitHub change impact and PR review context."""

from __future__ import annotations

import os
from typing import Any, Protocol

from src.repositories.github_research_cache_repository import (
    GitHubResearchCacheRepository,
)
from src.web.github_cache_policy import GitHubResearchCachePolicy
from src.web.github_history import GitHubHistoryService
from src.web.github_reader import parse_github_url


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _repository(repo_url: str) -> str:
    target = parse_github_url(repo_url)
    return target.repository if target is not None else str(repo_url or "")


class ChangeImpactDelegate(Protocol):
    def analyze(
        self,
        repo_url: str,
        base: str,
        head: str,
        *,
        max_files: int | None = None,
        max_symbols: int | None = None,
        depth: int = 2,
        max_impact_files: int = 40,
        max_edges: int = 160,
    ) -> dict[str, Any]: ...


class PRReviewContextDelegate(Protocol):
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
    ) -> dict[str, Any]: ...


class CachedGitHubChangeImpactService:
    """Cache only after base/head have been resolved to immutable commit SHAs."""

    def __init__(
        self,
        delegate: ChangeImpactDelegate,
        history_service: GitHubHistoryService,
        cache_repository: GitHubResearchCacheRepository,
        cache_policy: GitHubResearchCachePolicy | None = None,
    ) -> None:
        self.delegate = delegate
        self.history_service = history_service
        self.cache_repository = cache_repository
        self.cache_policy = cache_policy or GitHubResearchCachePolicy.from_env()

    def analyze(
        self,
        repo_url: str,
        base: str,
        head: str,
        *,
        max_files: int | None = None,
        max_symbols: int | None = None,
        depth: int = 2,
        max_impact_files: int = 40,
        max_edges: int = 160,
    ) -> dict[str, Any]:
        base_ref = self.history_service.resolve_ref(repo_url, base)
        if base_ref.get("ok") is not True:
            return base_ref
        head_ref = self.history_service.resolve_ref(repo_url, head)
        if head_ref.get("ok") is not True:
            return head_ref
        file_limit = max_files or _env_int(
            "GITHUB_CHANGE_IMPACT_MAX_FILES",
            20,
            minimum=1,
            maximum=50,
        )
        symbol_limit = max_symbols or _env_int(
            "GITHUB_CHANGE_IMPACT_MAX_SYMBOLS",
            100,
            minimum=1,
            maximum=300,
        )
        identity = {
            "repository": _repository(repo_url),
            "base_sha": str(base_ref.get("commit_sha") or ""),
            "head_sha": str(head_ref.get("commit_sha") or ""),
            "max_files": max(1, min(int(file_limit), 50)),
            "max_symbols": max(1, min(int(symbol_limit), 300)),
            "depth": max(1, min(int(depth), 4)),
            "max_impact_files": max(1, min(int(max_impact_files), 100)),
            "max_edges": max(1, min(int(max_edges), 500)),
        }
        entry = self.cache_repository.get(
            "change_impact",
            identity,
            schema_version=self.cache_policy.schema_version,
            allow_partial=self.cache_policy.reuse_partial,
        )
        if entry is not None:
            return {
                **entry.payload,
                "cache_hit": True,
                "cache_source": "sqlite",
                "cache_status": entry.cache_status,
                "requested_base": base,
                "requested_head": head,
            }
        result = self.delegate.analyze(
            repo_url,
            identity["base_sha"],
            identity["head_sha"],
            max_files=identity["max_files"],
            max_symbols=identity["max_symbols"],
            depth=identity["depth"],
            max_impact_files=identity["max_impact_files"],
            max_edges=identity["max_edges"],
        )
        result = {
            **result,
            "requested_base": base,
            "requested_head": head,
        }
        ttl = self.cache_policy.ttl_for(result, cache_kind="change_impact")
        if ttl > 0:
            self.cache_repository.put(
                "change_impact",
                identity["repository"],
                identity,
                result,
                ttl_seconds=ttl,
                schema_version=self.cache_policy.schema_version,
            )
        return result


class CachedGitHubPRReviewContextService:
    """Short-lived durable cache for the fully composed PR evidence pack."""

    def __init__(
        self,
        delegate: PRReviewContextDelegate,
        cache_repository: GitHubResearchCacheRepository,
        cache_policy: GitHubResearchCachePolicy | None = None,
    ) -> None:
        self.delegate = delegate
        self.cache_repository = cache_repository
        self.cache_policy = cache_policy or GitHubResearchCachePolicy.from_env()

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
        identity = {
            "repository": _repository(repo_url),
            "number": int(number),
            "max_files": max(1, min(int(max_files), 50)),
            "max_symbols": max(1, min(int(max_symbols), 300)),
            "max_comments": max(1, min(int(max_comments), 100)),
            "max_reviews": max(1, min(int(max_reviews), 100)),
            "depth": max(1, min(int(depth), 4)),
            "max_impact_files": max(1, min(int(max_impact_files), 100)),
            "max_edges": max(1, min(int(max_edges), 500)),
            "max_provider_requests": max(
                1,
                min(int(max_provider_requests), 128),
            ),
            "max_pages_per_collection": max(
                1,
                min(int(max_pages_per_collection), 50),
            ),
        }
        entry = self.cache_repository.get(
            "pr_review_context",
            identity,
            schema_version=self.cache_policy.schema_version,
            allow_partial=self.cache_policy.reuse_partial,
        )
        if entry is not None:
            return {
                **entry.payload,
                "cache_hit": True,
                "cache_source": "sqlite",
                "cache_status": entry.cache_status,
            }
        result = self.delegate.build(
            repo_url,
            number,
            max_files=identity["max_files"],
            max_symbols=identity["max_symbols"],
            max_comments=identity["max_comments"],
            max_reviews=identity["max_reviews"],
            depth=identity["depth"],
            max_impact_files=identity["max_impact_files"],
            max_edges=identity["max_edges"],
            max_provider_requests=identity["max_provider_requests"],
            max_pages_per_collection=identity["max_pages_per_collection"],
        )
        ttl = self.cache_policy.ttl_for(result, cache_kind="pr_review_context")
        if ttl > 0:
            self.cache_repository.put(
                "pr_review_context",
                identity["repository"],
                identity,
                result,
                ttl_seconds=ttl,
                schema_version=self.cache_policy.schema_version,
            )
        return result
