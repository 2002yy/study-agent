"""Repository graph queries layered over durable GitHub snapshots."""

from __future__ import annotations

from typing import Any

from src.application.github_snapshot_service import GitHubSnapshotService
from src.web.repository_graph import RepositoryGraphIndex


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


class GitHubGraphService:
    def __init__(self, snapshot_service: GitHubSnapshotService) -> None:
        self.snapshot_service = snapshot_service
        self._indexes: dict[str, RepositoryGraphIndex] = {}

    def _index(self, snapshot: dict[str, Any]) -> RepositoryGraphIndex:
        key = _index_key(snapshot)
        index = self._indexes.get(key)
        if index is None:
            index = RepositoryGraphIndex(snapshot)
            self._indexes[key] = index
        return index

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
        snapshot = self.snapshot_service.snapshot(
            repo_url,
            query=focused_symbol,
            ref=ref,
        )
        if snapshot.get("ok") is not True:
            return {**snapshot, "symbol": focused_symbol}
        inspected = self._index(snapshot).inspect(
            focused_symbol,
            top_k=max(1, min(top_k, 50)),
        )
        return {
            **inspected,
            "snapshot_run_id": str(snapshot.get("snapshot_run_id") or ""),
            "cache_hit": bool(snapshot.get("cache_hit")),
            "cache_mode": str(snapshot.get("cache_mode") or ""),
        }
