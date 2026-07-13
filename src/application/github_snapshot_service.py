"""Persistent GitHub repository snapshots with bounded follow-up reuse."""

from __future__ import annotations

import os
import re
from typing import Any

from src.repositories.github_snapshot_repository import GitHubSnapshotRepository
from src.web.github_code_index import GitHubCodeIndex
from src.web.github_reader import parse_github_url
from src.web.github_snapshot import GitHubRepositorySnapshotter


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]+")


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _focused(value: str) -> str:
    return " ".join(str(value or "").split())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TOKEN_PATTERN.findall(value or "")
            if token.strip()
        )
    )


def _followup_subset(
    result: dict[str, Any],
    *,
    query: str,
    max_files: int,
) -> list[dict[str, Any]]:
    tokens = _tokens(query)
    if not tokens:
        return []
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for raw in result.get("files", []):
        if not isinstance(raw, dict):
            continue
        path = str(raw.get("path") or "")
        content = str(raw.get("content") or "")
        path_folded = path.casefold()
        content_folded = content.casefold()
        score = sum(
            8 if token in path_folded else 2 if token in content_folded else 0
            for token in tokens
        )
        if score <= 0:
            continue
        ranked.append((score, path, dict(raw)))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [item for _score, _path, item in ranked[:max_files]]


def _index_key(snapshot: dict[str, Any]) -> str:
    run_id = str(snapshot.get("snapshot_run_id") or "")
    tree_sha = str(snapshot.get("tree_sha") or "")
    files = ",".join(
        f"{item.get('path', '')}:{item.get('sha', '')}"
        for item in snapshot.get("files", [])
        if isinstance(item, dict)
    )
    return f"{run_id}:{tree_sha}:{files}"


class GitHubSnapshotService:
    def __init__(
        self,
        repository: GitHubSnapshotRepository,
        snapshotter: GitHubRepositorySnapshotter | None = None,
    ) -> None:
        self.repository = repository
        self.snapshotter = snapshotter or GitHubRepositorySnapshotter()
        self._indexes: dict[str, GitHubCodeIndex] = {}

    def snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        target = parse_github_url(repo_url)
        if target is None:
            return {
                "ok": False,
                "error": "unsupported_github_url",
                "url": str(repo_url or ""),
            }
        focused_query = _focused(query)
        focused_ref = _focused(ref or target.ref)
        ttl = _env_int(
            "GITHUB_SNAPSHOT_CACHE_TTL_SECONDS",
            1800,
            minimum=0,
            maximum=86400,
        )
        if not force_refresh and ttl > 0:
            exact = self.repository.find_exact(
                repository=target.repository,
                ref=focused_ref,
                query=focused_query,
                max_age_seconds=ttl,
            )
            if exact is not None:
                return {
                    **dict(exact.result),
                    "snapshot_run_id": exact.id,
                    "cache_hit": True,
                    "cache_mode": "exact",
                }

            previous = self.repository.find_latest(
                repository=target.repository,
                ref=focused_ref,
                max_age_seconds=ttl,
            )
            if previous is not None and focused_query:
                files = _followup_subset(
                    previous.result,
                    query=focused_query,
                    max_files=_env_int(
                        "GITHUB_SNAPSHOT_FOLLOWUP_MAX_FILES",
                        12,
                        minimum=1,
                        maximum=50,
                    ),
                )
                if files:
                    return {
                        **dict(previous.result),
                        "query": focused_query,
                        "files": files,
                        "file_count": len(files),
                        "used_chars": sum(
                            len(str(item.get("content") or "")) for item in files
                        ),
                        "snapshot_run_id": previous.id,
                        "cache_hit": True,
                        "cache_mode": "followup_subset",
                        "reused_snapshot_id": previous.id,
                    }

        run = self.repository.create(
            {
                "repository": target.repository,
                "repo_url": str(repo_url or ""),
                "ref": focused_ref,
                "query": focused_query,
                "force_refresh": force_refresh,
            }
        )
        result = self.snapshotter.snapshot(
            repo_url,
            query=focused_query,
            ref=focused_ref,
        )
        result = {
            **dict(result),
            "snapshot_run_id": run.id,
            "cache_hit": False,
            "cache_mode": "fresh",
        }
        if result.get("ok") is True:
            completed = self.repository.complete(run.id, result)
            return dict(completed.result)
        self.repository.fail(run.id, str(result.get("error") or "snapshot_failed"))
        return result

    def search_repository(
        self,
        repo_url: str,
        query: str,
        *,
        ref: str = "",
        top_k: int = 12,
    ) -> dict[str, Any]:
        focused_query = _focused(query)
        if not focused_query:
            return {
                "ok": False,
                "error": "empty_query",
                "query": focused_query,
                "results": [],
            }
        snapshot = self.snapshot(
            repo_url,
            query=focused_query,
            ref=ref,
        )
        if snapshot.get("ok") is not True:
            return {
                **snapshot,
                "query": focused_query,
                "results": [],
            }
        key = _index_key(snapshot)
        index = self._indexes.get(key)
        if index is None:
            index = GitHubCodeIndex.from_snapshot(snapshot)
            self._indexes[key] = index
        searched = index.search(focused_query, top_k=top_k)
        return {
            "ok": True,
            "mode": "local_snapshot_hybrid",
            "repository": str(snapshot.get("repository") or ""),
            "ref": str(snapshot.get("ref") or ""),
            "tree_sha": str(snapshot.get("tree_sha") or ""),
            "snapshot_run_id": str(snapshot.get("snapshot_run_id") or ""),
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_mode": str(snapshot.get("cache_mode") or ""),
            **searched,
        }

    def get(self, run_id: str) -> dict[str, Any]:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"GitHub snapshot not found: {run_id}")
        return {
            "id": run.id,
            "status": run.status,
            "request": run.request,
            "result": run.result,
            "error": run.error,
            "version": run.version,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "completed_at": run.completed_at,
        }

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "id": run.id,
                "status": run.status,
                "request": run.request,
                "result": run.result,
                "error": run.error,
                "version": run.version,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
                "completed_at": run.completed_at,
            }
            for run in self.repository.list(limit=limit)
        ]
