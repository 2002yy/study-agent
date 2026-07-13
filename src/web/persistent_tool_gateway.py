"""Production web gateway that reuses persistent GitHub repository snapshots."""

from __future__ import annotations

from typing import Any

from src.application.github_snapshot_service import GitHubSnapshotService
from src.web.tool_gateway import GeneralWebGateway


class PersistentGeneralWebGateway(GeneralWebGateway):
    def __init__(self, snapshot_service: GitHubSnapshotService) -> None:
        self.snapshot_service = snapshot_service
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
