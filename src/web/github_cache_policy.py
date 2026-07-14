"""Policy for durable GitHub research cache reuse and retention."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GitHubResearchCachePolicy:
    complete_ttl_seconds: int = 300
    partial_ttl_seconds: int = 30
    context_ttl_seconds: int = 180
    log_ttl_seconds: int = 60
    reuse_partial: bool = False
    schema_version: int = 1

    @classmethod
    def from_env(cls) -> "GitHubResearchCachePolicy":
        return cls(
            complete_ttl_seconds=_env_int(
                "GITHUB_RESEARCH_CACHE_TTL_SECONDS",
                300,
                minimum=0,
                maximum=86_400,
            ),
            partial_ttl_seconds=_env_int(
                "GITHUB_RESEARCH_PARTIAL_CACHE_TTL_SECONDS",
                30,
                minimum=0,
                maximum=3_600,
            ),
            context_ttl_seconds=_env_int(
                "GITHUB_RESEARCH_CONTEXT_CACHE_TTL_SECONDS",
                180,
                minimum=0,
                maximum=86_400,
            ),
            log_ttl_seconds=_env_int(
                "GITHUB_RESEARCH_LOG_CACHE_TTL_SECONDS",
                60,
                minimum=0,
                maximum=3_600,
            ),
            reuse_partial=_env_flag(
                "GITHUB_RESEARCH_CACHE_REUSE_PARTIAL",
                default=False,
            ),
            schema_version=_env_int(
                "GITHUB_RESEARCH_CACHE_SCHEMA_VERSION",
                1,
                minimum=1,
                maximum=100,
            ),
        )

    def ttl_for(self, result: dict[str, Any], *, cache_kind: str) -> int:
        if str(result.get("provider_status") or "") == "partial":
            return self.partial_ttl_seconds
        if cache_kind == "pr_review_context":
            return self.context_ttl_seconds
        if cache_kind == "ci_logs":
            return self.log_ttl_seconds
        return self.complete_ttl_seconds
