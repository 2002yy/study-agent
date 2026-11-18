"""Production HEAD-tree and blob readers for LearningFreshnessService.

Both adapters are read-only and keep small bounded in-memory caches so a
resume projection never duplicates GitHub calls across Claim bindings of
the same repository/commit.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from src.web.github_history import GitHubHistoryService
from src.web.github_reader import _api, _request_json, parse_github_url


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _http_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        if exc.code == 404:
            return "not_found"
        if exc.code in {401, 403}:
            return "unavailable"
        return f"github_http_{exc.code}"
    if isinstance(exc, URLError):
        return "unreachable"
    return f"{type(exc).__name__}: {exc}"


class GitHubFreshnessHeadResolver:
    """Resolve a repository HEAD commit and its recursive blob-sha tree."""

    def __init__(
        self,
        history_service: GitHubHistoryService | None = None,
        *,
        request_json: Callable[..., Any] | None = None,
    ) -> None:
        self.history_service = history_service or GitHubHistoryService()
        self.request_json = request_json or _request_json
        self._tree_cache: dict[str, tuple[float, dict[str, str]]] = {}

    def resolve_head(self, repo_url: str, ref: str = "") -> dict[str, Any]:
        target = parse_github_url(repo_url)
        if target is None:
            return {
                "ok": False,
                "error": "unsupported_github_url",
                "url": str(repo_url or ""),
            }
        resolved = self.history_service.resolve_ref(repo_url, ref)
        if not resolved.get("ok"):
            return {
                "ok": False,
                "commit_sha": str(resolved.get("commit_sha") or ""),
                "error": str(
                    resolved.get("error") or resolved.get("status") or "head_resolution_failed"
                ),
            }
        commit_sha = str(resolved.get("commit_sha") or "")
        tree = self._load_tree(target, commit_sha)
        if tree is None:
            return {
                "ok": False,
                "commit_sha": commit_sha,
                "error": "tree_fetch_failed",
            }
        return {"ok": True, "commit_sha": commit_sha, "tree": tree}

    def _load_tree(
        self, target: Any, commit_sha: str
    ) -> dict[str, str] | None:
        repository = f"{target.owner}/{target.repo}"
        cache_key = f"{repository}:{commit_sha}"
        cached = self._tree_cache.get(cache_key)
        if cached is not None:
            inserted, cached_tree = cached
            ttl = _env_int(
                "GITHUB_FRESHNESS_TREE_TTL_SECONDS",
                900,
                minimum=0,
                maximum=86400,
            )
            if ttl <= 0 or time.monotonic() - inserted < ttl:
                return cached_tree
        try:
            payload = self.request_json(
                _api(
                    "/repos/"
                    f"{quote(target.owner, safe='')}/"
                    f"{quote(target.repo, safe='')}"
                    f"/git/trees/{quote(commit_sha, safe='')}",
                    recursive=1,
                ),
                max_bytes=6_000_000,
            )
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        entries = payload.get("tree")
        if not isinstance(entries, list):
            return None
        if str(payload.get("truncated") or "").lower() in {"true", "1"}:
            return None
        tree: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") != "blob":
                continue
            path = entry.get("path")
            sha = entry.get("sha")
            if isinstance(path, str) and isinstance(sha, str):
                tree[path] = sha
        self._tree_cache[cache_key] = (time.monotonic(), tree)
        return tree


class GitHubFreshnessBlobReader:
    """Read decoded git blob text by exact blob sha with bounded cache."""

    def __init__(self, *, request_json: Callable[..., Any] | None = None) -> None:
        self.request_json = request_json or _request_json
        self._blob_cache: dict[str, tuple[float, str]] = {}

    def read_blob(self, repo_url: str, sha: str) -> str:
        cached = self._blob_cache.get(sha)
        if cached is not None:
            inserted, content = cached
            ttl = _env_int(
                "GITHUB_FRESHNESS_BLOB_TTL_SECONDS",
                900,
                minimum=0,
                maximum=86400,
            )
            if ttl <= 0 or time.monotonic() - inserted < ttl:
                return content
        target = parse_github_url(repo_url)
        if target is None:
            raise ValueError(f"unsupported_github_url: {repo_url}")
        try:
            payload = self.request_json(
                _api(
                    f"/repos/{quote(target.owner, safe='')}"
                    f"/{quote(target.repo, safe='')}"
                    f"/git/blobs/{quote(sha, safe='')}"
                ),
                max_bytes=4_000_000,
            )
        except Exception as exc:
            raise ValueError(f"blob_read_failed: {_http_error(exc)}") from exc
        if not isinstance(payload, dict):
            raise ValueError("blob_response_invalid")
        encoded = payload.get("content")
        if isinstance(encoded, str) and payload.get("encoding") == "base64":
            content = base64.b64decode(encoded.encode("ascii")).decode(
                "utf-8", errors="replace"
            )
        elif isinstance(encoded, str):
            content = encoded
        else:
            raise ValueError("blob_content_missing")
        if len(self._blob_cache) < _env_int(
            "GITHUB_FRESHNESS_BLOB_CACHE_MAX_ENTRIES",
            64,
            minimum=1,
            maximum=4096,
        ):
            self._blob_cache[sha] = (time.monotonic(), content)
        elif sha not in self._blob_cache:
            oldest = min(self._blob_cache, key=lambda key: self._blob_cache[key][0])
            self._blob_cache.pop(oldest, None)
            self._blob_cache[sha] = (time.monotonic(), content)
        return content
