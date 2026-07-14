"""Paginated GitHub work-item service with one shared provider request budget.

This production service extends the original bounded service without rewriting its
log-redaction behavior. Pull-request, issue, review-thread, check-run, workflow-run,
and workflow-job collections paginate deterministically. One mutable request budget
is shared by the complete composed operation so nested checks cannot silently exceed
the caller's provider budget.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.web.github_provider_pagination import (
    GitHubProviderRequestBudget,
    collect_rest_pages,
)
from src.web.github_reader import GitHubTarget, _api, _token, parse_github_url
from src.web.github_work_items import (
    GitHubWorkItemBudget,
    GitHubWorkItemService,
    _actor,
    _bounded_text,
    _provider_error,
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _repo_url(repository: str, fallback: str) -> str:
    full_name = str(repository or "").strip().strip("/")
    candidate = f"https://github.com/{full_name}" if full_name else fallback
    return candidate if parse_github_url(candidate) is not None else fallback


def _collection_partial(result: dict[str, Any]) -> bool:
    return str(result.get("stop_reason") or "") in {
        "provider_error",
        "request_budget_exhausted",
        "page_budget_exhausted",
    }


class PaginatedGitHubWorkItemService(GitHubWorkItemService):
    """Production work-item reader with pagination, budgets, and fork awareness."""

    def _budgeted_json(
        self,
        operation: str,
        url: str,
        request_budget: GitHubProviderRequestBudget,
        *,
        max_bytes: int = 8_000_000,
    ) -> tuple[Any | None, dict[str, str] | None]:
        if not request_budget.claim(operation):
            return None, _provider_error(
                operation,
                "provider_request_budget_exhausted",
            )
        return self._safe_json(operation, url, max_bytes=max_bytes)

    def _rest_collection(
        self,
        *,
        operation: str,
        path: str,
        limit: int,
        request_budget: GitHubProviderRequestBudget,
        key: str = "",
        params: dict[str, str | int] | None = None,
        max_bytes: int = 8_000_000,
    ) -> dict[str, Any]:
        query = dict(params or {})
        return collect_rest_pages(
            operation=operation,
            limit=limit,
            max_pages=request_budget.max_pages_per_collection,
            key=key,
            fetch_page=lambda page, per_page: self._budgeted_json(
                operation,
                _api(path, **query, page=page, per_page=per_page),
                request_budget,
                max_bytes=max_bytes,
            ),
        )

    def _review_threads_paginated(
        self,
        target: GitHubTarget,
        number: int,
        *,
        limit: int,
        request_budget: GitHubProviderRequestBudget,
    ) -> dict[str, Any]:
        if not _token():
            return {
                "status": "unavailable",
                "error": "github_review_threads_require_token",
                "threads": [],
                "truncated": False,
                "pagination": {
                    "pages_fetched": 0,
                    "stop_reason": "token_unavailable",
                },
            }
        if not callable(self.request_graphql):
            return {
                "status": "unavailable",
                "error": "github_graphql_adapter_unavailable",
                "threads": [],
                "truncated": False,
                "pagination": {
                    "pages_fetched": 0,
                    "stop_reason": "adapter_unavailable",
                },
            }

        bounded = max(1, min(int(limit), 100))
        first = max(1, min(bounded + 1, 100))
        query = """
        query ReviewThreads(
          $owner: String!, $repo: String!, $number: Int!,
          $first: Int!, $after: String
        ) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $number) {
              reviewThreads(first: $first, after: $after) {
                totalCount
                pageInfo { hasNextPage endCursor }
                nodes {
                  id isResolved isOutdated path line startLine diffSide
                  comments(first: 100) {
                    totalCount
                    pageInfo { hasNextPage endCursor }
                    nodes {
                      databaseId body createdAt updatedAt url
                      author { login }
                    }
                  }
                }
              }
            }
          }
        }
        """
        threads: list[dict[str, Any]] = []
        provider_errors: list[dict[str, str]] = []
        provider_thread_count = 0
        after: str | None = None
        pages_fetched = 0
        stop_reason = "provider_exhausted"
        has_next_page = False
        nested_comments_truncated = False

        for _page in range(1, request_budget.max_pages_per_collection + 1):
            operation = "pull_request_review_threads"
            if not request_budget.claim(operation):
                provider_errors.append(
                    _provider_error(operation, "provider_request_budget_exhausted")
                )
                stop_reason = "request_budget_exhausted"
                break
            try:
                payload = self.request_graphql(
                    query,
                    {
                        "owner": target.owner,
                        "repo": target.repo,
                        "number": number,
                        "first": first,
                        "after": after,
                    },
                )
            except Exception as exc:
                provider_errors.append(
                    _provider_error(operation, f"{type(exc).__name__}: {exc}")
                )
                stop_reason = "provider_error"
                break
            pages_fetched += 1
            if not isinstance(payload, dict) or payload.get("errors"):
                provider_errors.append(
                    _provider_error(operation, "github_review_threads_graphql_failed")
                )
                stop_reason = "provider_error"
                break
            data = _as_dict(payload.get("data"))
            repository = _as_dict(data.get("repository"))
            pull = _as_dict(repository.get("pullRequest"))
            raw = _as_dict(pull.get("reviewThreads"))
            provider_thread_count = max(
                provider_thread_count,
                int(raw.get("totalCount") or 0),
            )
            nodes = raw.get("nodes")
            page_nodes = [
                dict(item)
                for item in nodes
                if isinstance(item, dict)
            ] if isinstance(nodes, list) else []
            for item in page_nodes:
                comments_data = _as_dict(item.get("comments"))
                comment_nodes = comments_data.get("nodes")
                raw_comments = [
                    dict(comment)
                    for comment in comment_nodes
                    if isinstance(comment, dict)
                ] if isinstance(comment_nodes, list) else []
                provider_comment_count = int(
                    comments_data.get("totalCount") or len(raw_comments)
                )
                comments: list[dict[str, Any]] = []
                for comment in raw_comments:
                    body, body_truncated = _bounded_text(
                        comment.get("body"), max_chars=8_000
                    )
                    author = _as_dict(comment.get("author"))
                    comments.append(
                        {
                            "id": int(comment.get("databaseId") or 0),
                            "body": body,
                            "body_truncated": body_truncated,
                            "created_at": str(comment.get("createdAt") or ""),
                            "updated_at": str(comment.get("updatedAt") or ""),
                            "url": str(comment.get("url") or ""),
                            "author_login": str(author.get("login") or ""),
                        }
                    )
                comment_page_info = _as_dict(comments_data.get("pageInfo"))
                comments_truncated = (
                    provider_comment_count > len(comments)
                    or bool(comment_page_info.get("hasNextPage"))
                )
                nested_comments_truncated = (
                    nested_comments_truncated or comments_truncated
                )
                threads.append(
                    {
                        "id": str(item.get("id") or ""),
                        "is_resolved": bool(item.get("isResolved")),
                        "is_outdated": bool(item.get("isOutdated")),
                        "path": str(item.get("path") or ""),
                        "line": int(item.get("line") or 0),
                        "start_line": int(item.get("startLine") or 0),
                        "side": str(item.get("diffSide") or ""),
                        "comments": comments,
                        "provider_comment_count": provider_comment_count,
                        "comments_truncated": comments_truncated,
                    }
                )
                if len(threads) >= bounded + 1:
                    break
            if len(threads) >= bounded + 1:
                stop_reason = "item_budget_reached"
                has_next_page = True
                break
            page_info = _as_dict(raw.get("pageInfo"))
            has_next_page = bool(page_info.get("hasNextPage"))
            after = str(page_info.get("endCursor") or "") or None
            if not has_next_page:
                stop_reason = "provider_exhausted"
                break
            if not after:
                provider_errors.append(
                    _provider_error(operation, "github_graphql_cursor_missing")
                )
                stop_reason = "provider_error"
                break
        else:
            stop_reason = "page_budget_exhausted"

        visible = threads[:bounded]
        truncated = (
            len(threads) > bounded
            or provider_thread_count > len(visible)
            or has_next_page
            or nested_comments_truncated
            or stop_reason in {
                "page_budget_exhausted",
                "request_budget_exhausted",
                "provider_error",
            }
        )
        status = "resolved" if pages_fetched > 0 else "unavailable"
        return {
            "status": status,
            "error": str(provider_errors[0].get("error") or "")
            if provider_errors and pages_fetched == 0
            else "",
            "threads": visible,
            "thread_count": len(visible),
            "provider_thread_count": max(provider_thread_count, len(threads)),
            "unresolved_count": sum(not item["is_resolved"] for item in visible),
            "provider_errors": provider_errors,
            "truncated": bool(truncated),
            "pagination": {
                "pages_fetched": pages_fetched,
                "stop_reason": stop_reason,
                "max_pages": request_budget.max_pages_per_collection,
                "nested_comments_truncated": nested_comments_truncated,
            },
        }

    def _checks_for_commit(
        self,
        repo_url: str,
        *,
        requested_ref: str,
        commit_sha: str,
        tree_sha: str = "",
        max_runs: int,
        max_checks: int,
        max_jobs: int,
        include_jobs: bool,
        request_budget: GitHubProviderRequestBudget,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}

        check_pages = self._rest_collection(
            operation=f"check_runs:{target.repository}",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/commits/{quote(commit_sha, safe='')}/check-runs"
            ),
            limit=max_checks,
            request_budget=request_budget,
            key="check_runs",
        )
        run_pages = self._rest_collection(
            operation=f"workflow_runs:{target.repository}",
            path=f"/repos/{quote(target.owner)}/{quote(target.repo)}/actions/runs",
            limit=max_runs,
            request_budget=request_budget,
            key="workflow_runs",
            params={"head_sha": commit_sha},
        )
        checks = [self._check_run(item) for item in check_pages["items"]]
        runs = [self._workflow_run(item) for item in run_pages["items"]]
        provider_errors = [
            *check_pages["errors"],
            *run_pages["errors"],
        ]

        jobs: list[dict[str, Any]] = []
        job_pagination: list[dict[str, Any]] = []
        jobs_truncated = False
        if include_jobs:
            remaining = max_jobs
            for run in runs:
                if remaining <= 0:
                    jobs_truncated = True
                    break
                run_id = int(run.get("id") or 0)
                if run_id <= 0:
                    continue
                pages = self._rest_collection(
                    operation=f"workflow_jobs:{target.repository}:{run_id}",
                    path=(
                        f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                        f"/actions/runs/{run_id}/jobs"
                    ),
                    limit=remaining,
                    request_budget=request_budget,
                    key="jobs",
                )
                converted = [self._job(item) for item in pages["items"]]
                jobs.extend(converted)
                remaining = max_jobs - len(jobs)
                provider_errors.extend(pages["errors"])
                job_pagination.append(
                    {
                        "run_id": run_id,
                        "pages_fetched": pages["pages_fetched"],
                        "provider_count": pages["provider_count"],
                        "returned_count": len(converted),
                        "truncated": pages["truncated"],
                        "stop_reason": pages["stop_reason"],
                    }
                )
                jobs_truncated = jobs_truncated or bool(pages["truncated"])
                if request_budget.exhausted_operations:
                    jobs_truncated = True
                    break

        no_check_evidence = check_pages["pages_fetched"] == 0
        no_run_evidence = run_pages["pages_fetched"] == 0
        if no_check_evidence and no_run_evidence:
            return {
                "ok": False,
                "status": "unavailable",
                "repository": target.repository,
                "requested_ref": requested_ref,
                "commit_sha": commit_sha,
                "error": "github_checks_providers_unavailable",
                "provider_errors": provider_errors,
                "pagination": {
                    "check_runs": check_pages,
                    "workflow_runs": run_pages,
                    "workflow_jobs": job_pagination,
                },
                "provider_request_budget": request_budget.to_dict(),
            }

        partial = (
            bool(provider_errors)
            or _collection_partial(check_pages)
            or _collection_partial(run_pages)
            or any(
                str(item.get("stop_reason") or "")
                in {
                    "provider_error",
                    "request_budget_exhausted",
                    "page_budget_exhausted",
                }
                for item in job_pagination
            )
        )
        return {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if partial else "complete",
            "repository": target.repository,
            "evidence_repository": target.repository,
            "requested_ref": requested_ref,
            "commit_sha": commit_sha,
            "tree_sha": tree_sha,
            "check_runs": checks,
            "check_count": len(checks),
            "provider_check_count": int(check_pages["provider_count"]),
            "workflow_runs": runs,
            "workflow_run_count": len(runs),
            "provider_workflow_run_count": int(run_pages["provider_count"]),
            "jobs": jobs,
            "job_count": len(jobs),
            "provider_errors": provider_errors,
            "truncated": (
                bool(check_pages["truncated"])
                or bool(run_pages["truncated"])
                or jobs_truncated
            ),
            "pagination": {
                "check_runs": {
                    key: check_pages[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                },
                "workflow_runs": {
                    key: run_pages[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                },
                "workflow_jobs": job_pagination,
            },
            "budget": {
                "max_runs": max_runs,
                "max_checks": max_checks,
                "max_jobs": max_jobs,
                "include_jobs": include_jobs,
            },
            "provider_request_budget": request_budget.to_dict(),
        }

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
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        resolved = self.history_service.resolve_ref(repo_url, ref)
        if resolved.get("ok") is not True:
            return resolved
        item_budget = GitHubWorkItemBudget.from_env()
        run_limit = max(1, min(int(max_runs or item_budget.max_runs), 100))
        check_limit = max(1, min(int(max_checks or item_budget.max_checks), 100))
        job_limit = max(1, min(int(max_jobs or item_budget.max_jobs), 300))
        request_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        commit_sha = str(resolved.get("commit_sha") or "")
        cache_key = (
            f"checks-v2:{target.repository}:{commit_sha}:{run_limit}:{check_limit}:"
            f"{job_limit}:{int(include_jobs)}:{request_budget.max_requests}:"
            f"{request_budget.max_pages_per_collection}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        result = self._checks_for_commit(
            repo_url,
            requested_ref=str(resolved.get("requested_ref") or ""),
            commit_sha=commit_sha,
            tree_sha=str(resolved.get("tree_sha") or ""),
            max_runs=run_limit,
            max_checks=check_limit,
            max_jobs=job_limit,
            include_jobs=include_jobs,
            request_budget=request_budget,
        )
        return self._cache_put(cache_key, result)

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
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        pr_number = int(number)
        if pr_number <= 0:
            return {
                "ok": False,
                "status": "invalid",
                "error": "invalid_pull_request_number",
            }
        item_budget = GitHubWorkItemBudget.from_env()
        file_limit = max(1, min(int(max_files or item_budget.max_files), 100))
        patch_limit = max(
            1_000,
            min(int(max_patch_chars or item_budget.max_patch_chars), 1_000_000),
        )
        comment_limit = max(
            1,
            min(int(max_comments or item_budget.max_comments), 100),
        )
        review_limit = max(
            1,
            min(int(max_reviews or item_budget.max_reviews), 100),
        )
        request_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        cache_key = (
            f"pr-v2:{target.repository}:{pr_number}:{file_limit}:{patch_limit}:"
            f"{comment_limit}:{review_limit}:{int(include_checks)}:"
            f"{request_budget.max_requests}:{request_budget.max_pages_per_collection}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload, core_error = self._budgeted_json(
            "pull_request",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}/pulls/{pr_number}"
            ),
            request_budget,
        )
        if not isinstance(payload, dict):
            status = core_error["error"] if core_error else "failed"
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": status,
                    "repository": target.repository,
                    "number": pr_number,
                    "error": "github_pull_request_unavailable",
                    "provider_errors": [core_error] if core_error else [],
                    "provider_request_budget": request_budget.to_dict(),
                },
            )

        provider_errors: list[dict[str, str]] = []
        base = _as_dict(payload.get("base"))
        head = _as_dict(payload.get("head"))
        base_sha = str(base.get("sha") or "")
        head_sha = str(head.get("sha") or "")
        base_repo = _as_dict(base.get("repo"))
        head_repo = _as_dict(head.get("repo"))
        base_repository = str(base_repo.get("full_name") or target.repository)
        head_repository = str(head_repo.get("full_name") or "")
        base_repo_url = _repo_url(base_repository, repo_url)
        head_repo_url = _repo_url(head_repository, repo_url)
        cross_repository = bool(
            head_repository and head_repository != base_repository
        )

        files_pages = self._rest_collection(
            operation="pull_request_files",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/pulls/{pr_number}/files"
            ),
            limit=file_limit,
            request_budget=request_budget,
            max_bytes=12_000_000,
        )
        reviews_pages = self._rest_collection(
            operation="pull_request_reviews",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/pulls/{pr_number}/reviews"
            ),
            limit=review_limit,
            request_budget=request_budget,
        )
        inline_pages = self._rest_collection(
            operation="pull_request_review_comments",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/pulls/{pr_number}/comments"
            ),
            limit=comment_limit,
            request_budget=request_budget,
        )
        issue_comment_pages = self._rest_collection(
            operation="pull_request_issue_comments",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{pr_number}/comments"
            ),
            limit=comment_limit,
            request_budget=request_budget,
        )
        for collection in (
            files_pages,
            reviews_pages,
            inline_pages,
            issue_comment_pages,
        ):
            provider_errors.extend(collection["errors"])

        remaining_patch = patch_limit
        files: list[dict[str, Any]] = []
        for item in files_pages["items"]:
            converted = self._patch_file(item, patch_budget=remaining_patch)
            remaining_patch = max(
                0,
                remaining_patch - len(str(converted.get("patch") or "")),
            )
            files.append(converted)
        reviews = [self._review(item) for item in reviews_pages["items"]]
        inline_comments = [
            self._comment(item, inline=True) for item in inline_pages["items"]
        ]
        issue_comments = [
            self._comment(item) for item in issue_comment_pages["items"]
        ]

        review_threads = self._review_threads_paginated(
            target,
            pr_number,
            limit=comment_limit,
            request_budget=request_budget,
        )
        provider_errors.extend(review_threads.get("provider_errors", []))
        if review_threads.get("status") not in {"resolved", "unavailable"}:
            provider_errors.append(
                _provider_error(
                    "pull_request_review_threads",
                    str(review_threads.get("error") or "failed"),
                )
            )

        checks: dict[str, Any] = {"status": "not_requested", "ok": False}
        if include_checks and head_sha:
            checks = self._checks_for_commit(
                repo_url,
                requested_ref=head_sha,
                commit_sha=head_sha,
                max_runs=item_budget.max_runs,
                max_checks=item_budget.max_checks,
                max_jobs=item_budget.max_jobs,
                include_jobs=True,
                request_budget=request_budget,
            )
            if (
                checks.get("ok") is not True
                and cross_repository
                and request_budget.remaining_requests > 0
            ):
                fallback = self._checks_for_commit(
                    head_repo_url,
                    requested_ref=head_sha,
                    commit_sha=head_sha,
                    max_runs=item_budget.max_runs,
                    max_checks=item_budget.max_checks,
                    max_jobs=item_budget.max_jobs,
                    include_jobs=True,
                    request_budget=request_budget,
                )
                if fallback.get("ok") is True:
                    checks = {
                        **fallback,
                        "fallback_from_repository": target.repository,
                    }
                else:
                    provider_errors.extend(fallback.get("provider_errors", []))
            if checks.get("ok") is not True:
                provider_errors.append(
                    _provider_error(
                        "pull_request_checks",
                        str(checks.get("error") or "unavailable"),
                    )
                )

        base_commit = (
            self.history_service.commit(base_repo_url, base_sha)
            if base_sha
            else {}
        )
        head_commit = (
            self.history_service.commit(head_repo_url, head_sha)
            if head_sha
            else {}
        )
        if base_sha and base_commit.get("ok") is not True:
            provider_errors.append(
                _provider_error(
                    "pull_request_base_commit",
                    str(base_commit.get("error") or "unavailable"),
                )
            )
        if head_sha and head_commit.get("ok") is not True:
            provider_errors.append(
                _provider_error(
                    "pull_request_head_commit",
                    str(head_commit.get("error") or "unavailable"),
                )
            )

        body, body_truncated = _bounded_text(payload.get("body"), max_chars=20_000)
        collections = {
            "files": files_pages,
            "reviews": reviews_pages,
            "inline_comments": inline_pages,
            "issue_comments": issue_comment_pages,
        }
        partial = (
            bool(provider_errors)
            or bool(request_budget.exhausted_operations)
            or any(_collection_partial(item) for item in collections.values())
            or str(
                _as_dict(review_threads.get("pagination")).get("stop_reason") or ""
            )
            in {
                "provider_error",
                "request_budget_exhausted",
                "page_budget_exhausted",
            }
            or str(checks.get("provider_status") or "") == "partial"
        )
        result = {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if partial else "complete",
            "repository": target.repository,
            "number": pr_number,
            "title": str(payload.get("title") or ""),
            "body": body,
            "body_truncated": body_truncated,
            "state": str(payload.get("state") or ""),
            "draft": bool(payload.get("draft")),
            "merged": bool(payload.get("merged")),
            "mergeable": payload.get("mergeable"),
            "mergeable_state": str(payload.get("mergeable_state") or ""),
            "created_at": str(payload.get("created_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "closed_at": str(payload.get("closed_at") or ""),
            "merged_at": str(payload.get("merged_at") or ""),
            "url": str(payload.get("html_url") or ""),
            "user": _actor(payload.get("user")),
            "author_association": str(payload.get("author_association") or ""),
            "requested_reviewers": [
                _actor(item)
                for item in payload.get("requested_reviewers", [])
                if isinstance(item, dict)
            ],
            "labels": [
                str(item.get("name") or "")
                for item in payload.get("labels", [])
                if isinstance(item, dict)
            ],
            "base": {
                "ref": str(base.get("ref") or ""),
                "label": str(base.get("label") or ""),
                "commit_sha": base_sha,
                "repository": base_repository,
                "repository_url": base_repo_url,
                "commit": base_commit,
            },
            "head": {
                "ref": str(head.get("ref") or ""),
                "label": str(head.get("label") or ""),
                "commit_sha": head_sha,
                "repository": head_repository,
                "repository_url": head_repo_url,
                "is_cross_repository": cross_repository,
                "commit": head_commit,
            },
            "cross_repository": cross_repository,
            "commits": int(payload.get("commits") or 0),
            "changed_files": int(
                payload.get("changed_files") or files_pages["provider_count"]
            ),
            "additions": int(payload.get("additions") or 0),
            "deletions": int(payload.get("deletions") or 0),
            "files": files,
            "file_count": len(files),
            "provider_file_count": int(files_pages["provider_count"]),
            "reviews": reviews,
            "review_count": len(reviews),
            "provider_review_count": int(reviews_pages["provider_count"]),
            "inline_comments": inline_comments,
            "inline_comment_count": len(inline_comments),
            "provider_inline_comment_count": int(inline_pages["provider_count"]),
            "issue_comments": issue_comments,
            "issue_comment_count": len(issue_comments),
            "provider_issue_comment_count": int(
                issue_comment_pages["provider_count"]
            ),
            "review_threads": review_threads,
            "checks": checks,
            "checks_repository": str(
                checks.get("evidence_repository") or target.repository
            ),
            "provider_errors": provider_errors,
            "truncated": (
                any(bool(item["truncated"]) for item in collections.values())
                or any(item.get("patch_truncated") for item in files)
                or bool(review_threads.get("truncated"))
                or bool(checks.get("truncated"))
            ),
            "pagination": {
                name: {
                    key: value[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                }
                for name, value in collections.items()
            }
            | {
                "review_threads": _as_dict(review_threads.get("pagination")),
                "checks": _as_dict(checks.get("pagination")),
            },
            "budget": {
                "max_files": file_limit,
                "max_patch_chars": patch_limit,
                "max_comments": comment_limit,
                "max_reviews": review_limit,
                "include_checks": include_checks,
            },
            "provider_request_budget": request_budget.to_dict()
            | {"scope": "work_item_rest_graphql_collections"},
        }
        return self._cache_put(cache_key, result)

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
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        issue_number = int(number)
        if issue_number <= 0:
            return {"ok": False, "status": "invalid", "error": "invalid_issue_number"}
        item_budget = GitHubWorkItemBudget.from_env()
        comment_limit = max(
            1,
            min(int(max_comments or item_budget.max_comments), 100),
        )
        event_limit = max(1, min(int(max_events or item_budget.max_events), 100))
        request_budget = GitHubProviderRequestBudget.from_env(
            max_requests=max_provider_requests,
            max_pages_per_collection=max_pages_per_collection,
        )
        cache_key = (
            f"issue-v2:{target.repository}:{issue_number}:{comment_limit}:"
            f"{event_limit}:{request_budget.max_requests}:"
            f"{request_budget.max_pages_per_collection}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload, core_error = self._budgeted_json(
            "issue",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}/issues/{issue_number}"
            ),
            request_budget,
        )
        if not isinstance(payload, dict):
            status = core_error["error"] if core_error else "failed"
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": status,
                    "repository": target.repository,
                    "number": issue_number,
                    "error": "github_issue_unavailable",
                    "provider_errors": [core_error] if core_error else [],
                    "provider_request_budget": request_budget.to_dict(),
                },
            )

        comments_pages = self._rest_collection(
            operation="issue_comments",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{issue_number}/comments"
            ),
            limit=comment_limit,
            request_budget=request_budget,
        )
        events_pages = self._rest_collection(
            operation="issue_events",
            path=(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{issue_number}/events"
            ),
            limit=event_limit,
            request_budget=request_budget,
        )
        provider_errors = [
            *comments_pages["errors"],
            *events_pages["errors"],
        ]
        comments = [self._comment(item) for item in comments_pages["items"]]
        events: list[dict[str, Any]] = []
        for item in events_pages["items"]:
            label = _as_dict(item.get("label"))
            rename = _as_dict(item.get("rename"))
            events.append(
                {
                    "id": int(item.get("id") or 0),
                    "event": str(item.get("event") or ""),
                    "created_at": str(item.get("created_at") or ""),
                    "actor": _actor(item.get("actor")),
                    "commit_sha": str(item.get("commit_id") or ""),
                    "commit_url": str(item.get("commit_url") or ""),
                    "label": str(label.get("name") or ""),
                    "rename": {
                        "from": str(rename.get("from") or ""),
                        "to": str(rename.get("to") or ""),
                    },
                }
            )

        body, body_truncated = _bounded_text(payload.get("body"), max_chars=20_000)
        milestone = _as_dict(payload.get("milestone"))
        linked_commit_shas = sorted(
            {
                str(item.get("commit_sha") or "")
                for item in events
                if item.get("commit_sha")
            }
        )
        partial = (
            bool(provider_errors)
            or bool(request_budget.exhausted_operations)
            or _collection_partial(comments_pages)
            or _collection_partial(events_pages)
        )
        result = {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if partial else "complete",
            "repository": target.repository,
            "number": issue_number,
            "kind": (
                "pull_request"
                if isinstance(payload.get("pull_request"), dict)
                else "issue"
            ),
            "title": str(payload.get("title") or ""),
            "body": body,
            "body_truncated": body_truncated,
            "state": str(payload.get("state") or ""),
            "state_reason": str(payload.get("state_reason") or ""),
            "locked": bool(payload.get("locked")),
            "created_at": str(payload.get("created_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "closed_at": str(payload.get("closed_at") or ""),
            "url": str(payload.get("html_url") or ""),
            "user": _actor(payload.get("user")),
            "assignee": _actor(payload.get("assignee")),
            "assignees": [
                _actor(item)
                for item in payload.get("assignees", [])
                if isinstance(item, dict)
            ],
            "labels": [
                str(item.get("name") or "")
                for item in payload.get("labels", [])
                if isinstance(item, dict)
            ],
            "milestone": {
                "number": int(milestone.get("number") or 0),
                "title": str(milestone.get("title") or ""),
                "state": str(milestone.get("state") or ""),
                "due_on": str(milestone.get("due_on") or ""),
            },
            "comments": comments,
            "comment_count": len(comments),
            "provider_comment_count": int(comments_pages["provider_count"]),
            "events": events,
            "event_count": len(events),
            "provider_event_count": int(events_pages["provider_count"]),
            "linked_commit_shas": linked_commit_shas,
            "provider_errors": provider_errors,
            "truncated": bool(comments_pages["truncated"])
            or bool(events_pages["truncated"]),
            "pagination": {
                "comments": {
                    key: comments_pages[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                },
                "events": {
                    key: events_pages[key]
                    for key in (
                        "pages_fetched",
                        "provider_count",
                        "truncated",
                        "stop_reason",
                        "per_page",
                        "max_pages",
                    )
                },
            },
            "budget": {
                "max_comments": comment_limit,
                "max_events": event_limit,
            },
            "provider_request_budget": request_budget.to_dict()
            | {"scope": "work_item_rest_graphql_collections"},
        }
        return self._cache_put(cache_key, result)
