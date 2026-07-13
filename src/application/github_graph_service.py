"""Repository graph queries layered over durable GitHub snapshots."""

from __future__ import annotations

from typing import Any
from weakref import WeakKeyDictionary

from src.application.github_snapshot_service import GitHubSnapshotService
from src.web.repository_graph import RepositoryGraphIndex
from src.web.semantic_impact import SemanticImpactIndex


def _focused(value: str) -> str:
    return " ".join(str(value or "").split())


def _index_key(snapshot: dict[str, Any]) -> str:
    run_id = str(snapshot.get("snapshot_run_id") or "")
    tree_sha = str(snapshot.get("tree_sha") or "")
    files = ",".join(
        f"{item.get('path', '')}:{item.get('sha', '')}"
        for item in snapshot.get("files", [])
        if isinstance(item, dict)
    )
    return f"{run_id}:{tree_sha}:{files}"


def _ensure_root_file(
    result: dict[str, Any],
    *,
    max_files: int,
) -> dict[str, Any]:
    resolution = result.get("resolution")
    if not isinstance(resolution, dict):
        return result
    selected = resolution.get("selected")
    if not isinstance(selected, dict):
        return result
    identity = selected.get("symbol_identity")
    if not isinstance(identity, dict):
        return result
    path = str(identity.get("path") or "")
    if not path:
        return result
    files = [dict(item) for item in result.get("files", []) if isinstance(item, dict)]
    existing = next((item for item in files if item.get("path") == path), None)
    inserted = existing is None
    if existing is not None:
        reasons = {str(reason) for reason in existing.get("reasons", [])}
        reasons.add("root")
        existing["reasons"] = sorted(reasons)
        files.remove(existing)
        files.insert(0, existing)
    else:
        files.insert(
            0,
            {
                "path": path,
                "file_sha": str(identity.get("file_sha") or ""),
                "reasons": ["root"],
            },
        )
    bounded_files = max(1, min(max_files, 100))
    trimmed = len(files) > bounded_files
    files = files[:bounded_files]
    return {
        **result,
        "files": files,
        "truncated": bool(result.get("truncated")) or trimmed or inserted and trimmed,
        "stats": {
            **dict(result.get("stats") or {}),
            "file_count": len(files),
        },
    }


class GitHubGraphService:
    def __init__(self, snapshot_service: GitHubSnapshotService) -> None:
        self.snapshot_service = snapshot_service
        self._indexes: dict[str, RepositoryGraphIndex] = {}
        self._semantic_indexes: dict[str, SemanticImpactIndex] = {}

    def _index(self, snapshot: dict[str, Any]) -> RepositoryGraphIndex:
        key = _index_key(snapshot)
        index = self._indexes.get(key)
        if index is None:
            index = RepositoryGraphIndex(snapshot)
            self._indexes[key] = index
        return index

    def _semantic_index(self, snapshot: dict[str, Any]) -> SemanticImpactIndex:
        key = _index_key(snapshot)
        index = self._semantic_indexes.get(key)
        if index is None:
            index = SemanticImpactIndex(self._index(snapshot))
            self._semantic_indexes[key] = index
        return index

    def _snapshot(
        self,
        repo_url: str,
        query: str,
        *,
        ref: str = "",
    ) -> dict[str, Any]:
        return self.snapshot_service.snapshot(repo_url, query=query, ref=ref)

    def inspect(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        top_k: int = 20,
    ) -> dict[str, Any]:
        focused_symbol = _focused(symbol)
        if not focused_symbol:
            return {
                "ok": False,
                "error": "empty_symbol",
                "symbol": focused_symbol,
            }
        snapshot = self._snapshot(repo_url, focused_symbol, ref=ref)
        if snapshot.get("ok") is not True:
            return {**snapshot, "symbol": focused_symbol}
        inspected = self._semantic_index(snapshot).inspect(
            focused_symbol,
            top_k=max(1, min(top_k, 50)),
        )
        return {
            **inspected,
            "snapshot_run_id": str(snapshot.get("snapshot_run_id") or ""),
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_mode": str(snapshot.get("cache_mode") or ""),
        }

    def impact(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        depth: int = 2,
        max_files: int = 30,
        max_edges: int = 120,
    ) -> dict[str, Any]:
        focused_symbol = _focused(symbol)
        if not focused_symbol:
            return {
                "ok": False,
                "error": "empty_symbol",
                "symbol": focused_symbol,
            }
        snapshot = self._snapshot(repo_url, focused_symbol, ref=ref)
        if snapshot.get("ok") is not True:
            return {**snapshot, "symbol": focused_symbol}
        bounded_files = max(1, min(max_files, 100))
        result = self._semantic_index(snapshot).impact(
            focused_symbol,
            depth=max(1, min(depth, 4)),
            max_files=bounded_files,
            max_edges=max(1, min(max_edges, 500)),
        )
        result = _ensure_root_file(result, max_files=bounded_files)
        return {
            **result,
            "snapshot_run_id": str(snapshot.get("snapshot_run_id") or ""),
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_mode": str(snapshot.get("cache_mode") or ""),
        }


_services: WeakKeyDictionary[GitHubSnapshotService, GitHubGraphService] = (
    WeakKeyDictionary()
)


def graph_service_for(snapshot_service: GitHubSnapshotService) -> GitHubGraphService:
    service = _services.get(snapshot_service)
    if service is None:
        service = GitHubGraphService(snapshot_service)
        _services[snapshot_service] = service
    return service
