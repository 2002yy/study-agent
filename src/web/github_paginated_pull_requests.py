"""Paginated pull-request, review, fork, and check evidence composition."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.web.github_paginated_base import (
    as_dict,
    collection_partial,
    dict_errors,
    repository_url,
)
from src.web.github_paginated_checks import PaginatedGitHubChecksService
from src.web.github_provider_pagination import GitHubProviderRequestBudget
from src.web.github_reader import _api
from src.web.github_work_items import (
    GitHubWorkItemBudget,
    _actor,
    _bounded_text,
    _provider_error,
)


class PaginatedGitHubPullRequestService(PaginatedGitHubChecksService):
    """Add paginated PR collections and cross-repository evidence ownership."""

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
        base = as_dict(payload.get("base"))
        head = as_dict(payload.get("head"))
        base_sha = str(base.get("sha") or "")
        head_sha = str(head.get("sha") or "")
        base_repo = as_dict(base.get("repo"))
        head_repo = as_dict(head.get("repo"))
        base_repository = str(base_repo.get("full_name") or target.repository)
        head_repository = str(head_repo.get("full_name") or "")
        base_repo_url = repository_url(base_repository, repo_url)
        head_repo_url = repository_url(head_repository, repo_url)
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
            provider_errors.extend(dict_errors(collection.get("errors")))

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
        provider_errors.extend(dict_errors(review_threads.get("provider_errors")))
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
                    provider_errors.extend(
                        dict_errors(fallback.get("provider_errors"))
                    )
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
            or any(collection_partial(item) for item in collections.values())
            or str(
                as_dict(review_threads.get("pagination")).get("stop_reason") or ""
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
                "review_threads": as_dict(review_threads.get("pagination")),
                "checks": as_dict(checks.get("pagination")),
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
