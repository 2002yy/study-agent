"""Production web gateway that reuses persistent GitHub repository snapshots."""

from __future__ import annotations

from typing import Any

from src.application.github_graph_service import graph_service_for
from src.application.github_snapshot_service import GitHubSnapshotService
from src.web.tool_gateway import GeneralWebGateway


class PersistentGeneralWebGateway(GeneralWebGateway):
    def __init__(self, snapshot_service: GitHubSnapshotService) -> None:
        self.snapshot_service = snapshot_service
        self.graph_service = graph_service_for(snapshot_service)
        super().__init__(
            github_snapshotter=snapshot_service,  # type: ignore[arg-type]
        )

    def github_search(
        self,
        repo_url: str,
        query: str,
        *,
        max_results: int = 8,
    ) -> dict[str, Any]:
        local = self.snapshot_service.search_repository(
            repo_url,
            query,
            top_k=max(1, min(max_results, 20)),
        )
        if local.get("ok") is True and int(local.get("result_count") or 0) > 0:
            return local
        remote = super().github_search(
            repo_url,
            query,
            max_results=max_results,
        )
        if remote.get("ok") is True:
            return {
                **remote,
                "local_snapshot": local,
            }
        return local if local.get("ok") is not True else remote

    def github_structure(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        max_results: int = 20,
    ) -> dict[str, Any]:
        return self.graph_service.inspect(
            repo_url,
            symbol,
            ref=ref,
            top_k=max(1, min(max_results, 50)),
        )

    def github_impact(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        depth: int = 2,
        max_files: int = 30,
        max_edges: int = 120,
    ) -> dict[str, Any]:
        return self.graph_service.impact(
            repo_url,
            symbol,
            ref=ref,
            depth=max(1, min(depth, 4)),
            max_files=max(1, min(max_files, 100)),
            max_edges=max(1, min(max_edges, 500)),
        )
