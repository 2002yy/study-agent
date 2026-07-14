"""Shared paginated GitHub provider primitives and review-thread reading."""

from __future__ import annotations

from typing import Any

from src.web.github_provider_pagination import (
    GitHubProviderRequestBudget,
    collect_rest_pages,
)
from src.web.github_reader import GitHubTarget, _api, _token, parse_github_url
from src.web.github_work_items import (
    GitHubWorkItemService,
    _bounded_text,
    _provider_error,
)


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def dict_errors(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {str(key): str(item_value) for key, item_value in item.items()}
        for item in value
        if isinstance(item, dict)
    ]


def repository_url(repository: str, fallback: str) -> str:
    full_name = str(repository or "").strip().strip("/")
    candidate = f"https://github.com/{full_name}" if full_name else fallback
    return candidate if parse_github_url(candidate) is not None else fallback


def collection_partial(result: dict[str, Any]) -> bool:
    return str(result.get("stop_reason") or "") in {
        "provider_error",
        "request_budget_exhausted",
        "page_budget_exhausted",
    }


class PaginatedGitHubBase(GitHubWorkItemService):
    """Base service that owns bounded REST and GraphQL collection reads."""

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
            data = as_dict(payload.get("data"))
            repository = as_dict(data.get("repository"))
            pull = as_dict(repository.get("pullRequest"))
            raw = as_dict(pull.get("reviewThreads"))
            provider_thread_count = max(
                provider_thread_count,
                int(raw.get("totalCount") or 0),
            )
            nodes = raw.get("nodes")
            page_nodes = (
                [dict(item) for item in nodes if isinstance(item, dict)]
                if isinstance(nodes, list)
                else []
            )
            for item in page_nodes:
                comments_data = as_dict(item.get("comments"))
                comment_nodes = comments_data.get("nodes")
                raw_comments = (
                    [
                        dict(comment)
                        for comment in comment_nodes
                        if isinstance(comment, dict)
                    ]
                    if isinstance(comment_nodes, list)
                    else []
                )
                provider_comment_count = int(
                    comments_data.get("totalCount") or len(raw_comments)
                )
                comments: list[dict[str, Any]] = []
                for comment in raw_comments:
                    body, body_truncated = _bounded_text(
                        comment.get("body"), max_chars=8_000
                    )
                    author = as_dict(comment.get("author"))
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
                comment_page_info = as_dict(comments_data.get("pageInfo"))
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
            page_info = as_dict(raw.get("pageInfo"))
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
            or stop_reason
            in {
                "page_budget_exhausted",
                "request_budget_exhausted",
                "provider_error",
            }
        )
        status = "resolved" if pages_fetched > 0 else "unavailable"
        return {
            "status": status,
            "error": (
                str(provider_errors[0].get("error") or "")
                if provider_errors and pages_fetched == 0
                else ""
            ),
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
