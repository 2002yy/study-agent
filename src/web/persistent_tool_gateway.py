"""Production web gateway with persistent GitHub source, history, work-item, and change research."""

from __future__ import annotations

from typing import Any

from src.application.github_graph_service import graph_service_for
from src.application.github_snapshot_service import GitHubSnapshotService
from src.web.github_change_impact import GitHubChangeImpactService
from src.web.github_history import GitHubHistoryService
from src.web.github_paginated_work_items import PaginatedGitHubWorkItemService
from src.web.github_pr_review_context import GitHubPRReviewContextService
from src.web.tool_gateway import GeneralWebGateway


class PersistentGeneralWebGateway(GeneralWebGateway):
    def __init__(
        self,
        snapshot_service: GitHubSnapshotService,
        history_service: GitHubHistoryService | None = None,
        work_item_service: PaginatedGitHubWorkItemService | None = None,
    ) -> None:
        self.snapshot_service = snapshot_service
        self.graph_service = graph_service_for(snapshot_service)
        self.history_service = history_service or GitHubHistoryService()
        self.work_item_service = work_item_service or PaginatedGitHubWorkItemService(
            self.history_service
        )
        self.change_impact_service = GitHubChangeImpactService(
            self.history_service,
            self.snapshot_service,
            getattr(self.work_item_service, "cache_repository", None),
        )
        self.pr_review_context_service = GitHubPRReviewContextService(
            self.work_item_service,
            self.change_impact_service,
        )
        super().__init__(github_snapshotter=snapshot_service)  # type: ignore[arg-type]

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
        remote = super().github_search(repo_url, query, max_results=max_results)
        if remote.get("ok") is True:
            return {**remote, "local_snapshot": local}
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

    def github_ref(self, repo_url: str, *, ref: str = "") -> dict[str, Any]:
        return self.history_service.resolve_ref(repo_url, ref)

    def github_commit(self, repo_url: str, *, ref: str = "") -> dict[str, Any]:
        return self.history_service.commit(repo_url, ref)

    def github_compare(
        self,
        repo_url: str,
        base: str,
        head: str,
        *,
        max_files: int = 100,
        max_patch_chars: int = 120000,
    ) -> dict[str, Any]:
        return self.history_service.compare(
            repo_url,
            base,
            head,
            max_files=max(1, min(max_files, 300)),
            max_patch_chars=max(1000, min(max_patch_chars, 1000000)),
        )

    def github_change_impact(
        self,
        repo_url: str,
        base: str,
        head: str,
        *,
        max_files: int = 20,
        max_symbols: int = 100,
        depth: int = 2,
        max_impact_files: int = 40,
        max_edges: int = 160,
    ) -> dict[str, Any]:
        return self.change_impact_service.analyze(
            repo_url,
            base,
            head,
            max_files=max(1, min(max_files, 50)),
            max_symbols=max(1, min(max_symbols, 300)),
            depth=max(1, min(depth, 4)),
            max_impact_files=max(1, min(max_impact_files, 100)),
            max_edges=max(1, min(max_edges, 500)),
        )

    def github_pr_review_context(
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
        return self.pr_review_context_service.build(
            repo_url,
            number,
            max_files=max(1, min(max_files, 50)),
            max_symbols=max(1, min(max_symbols, 300)),
            max_comments=max(1, min(max_comments, 100)),
            max_reviews=max(1, min(max_reviews, 100)),
            depth=max(1, min(depth, 4)),
            max_impact_files=max(1, min(max_impact_files, 100)),
            max_edges=max(1, min(max_edges, 500)),
            max_provider_requests=max(1, min(max_provider_requests, 128)),
            max_pages_per_collection=max(1, min(max_pages_per_collection, 50)),
        )

    def github_blame(
        self,
        repo_url: str,
        path: str,
        *,
        ref: str = "",
        start_line: int = 1,
        end_line: int = 0,
    ) -> dict[str, Any]:
        return self.history_service.blame(
            repo_url,
            path,
            ref=ref,
            start_line=max(1, start_line),
            end_line=max(0, end_line),
        )

    def github_pr(
        self,
        repo_url: str,
        number: int,
        *,
        max_files: int = 50,
        max_patch_chars: int = 120000,
        max_comments: int = 100,
        max_reviews: int = 100,
        include_checks: bool = True,
        max_provider_requests: int = 24,
        max_pages_per_collection: int = 10,
    ) -> dict[str, Any]:
        return self.work_item_service.pull_request(
            repo_url,
            number,
            max_files=max(1, min(max_files, 100)),
            max_patch_chars=max(1000, min(max_patch_chars, 1000000)),
            max_comments=max(1, min(max_comments, 100)),
            max_reviews=max(1, min(max_reviews, 100)),
            include_checks=include_checks,
            max_provider_requests=max(1, min(max_provider_requests, 128)),
            max_pages_per_collection=max(1, min(max_pages_per_collection, 50)),
        )

    def github_issue(
        self,
        repo_url: str,
        number: int,
        *,
        max_comments: int = 100,
        max_events: int = 100,
        max_provider_requests: int = 12,
        max_pages_per_collection: int = 10,
    ) -> dict[str, Any]:
        return self.work_item_service.issue(
            repo_url,
            number,
            max_comments=max(1, min(max_comments, 100)),
            max_events=max(1, min(max_events, 100)),
            max_provider_requests=max(1, min(max_provider_requests, 128)),
            max_pages_per_collection=max(1, min(max_pages_per_collection, 50)),
        )

    def github_checks(
        self,
        repo_url: str,
        *,
        ref: str = "",
        max_runs: int = 20,
        max_checks: int = 100,
        max_jobs: int = 100,
        include_jobs: bool = True,
        max_provider_requests: int = 16,
        max_pages_per_collection: int = 10,
    ) -> dict[str, Any]:
        return self.work_item_service.checks(
            repo_url,
            ref=ref,
            max_runs=max(1, min(max_runs, 100)),
            max_checks=max(1, min(max_checks, 100)),
            max_jobs=max(1, min(max_jobs, 300)),
            include_jobs=include_jobs,
            max_provider_requests=max(1, min(max_provider_requests, 128)),
            max_pages_per_collection=max(1, min(max_pages_per_collection, 50)),
        )

    def github_ci_logs(
        self,
        repo_url: str,
        job_id: int,
        *,
        max_chars: int = 40000,
        max_lines: int = 400,
    ) -> dict[str, Any]:
        return self.work_item_service.ci_logs(
            repo_url,
            job_id,
            max_chars=max(1000, min(max_chars, 200000)),
            max_lines=max(20, min(max_lines, 2000)),
        )
