"""Paginated GitHub work-item production service.

The implementation is split by ownership:
- ``github_paginated_base`` owns request accounting and review-thread cursors;
- ``github_paginated_checks`` owns checks, runs, and jobs;
- ``github_paginated_pull_requests`` owns PR and cross-fork composition;
- this module adds issue collections and exposes the final service type.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from src.web.github_paginated_base import as_dict, collection_partial, dict_errors
from src.web.github_paginated_pull_requests import PaginatedGitHubPullRequestService
from src.web.github_provider_pagination import GitHubProviderRequestBudget
from src.web.github_reader import _api
from src.web.github_work_items import (
    GitHubWorkItemBudget,
    _actor,
    _bounded_text,
)


class PaginatedGitHubWorkItemService(PaginatedGitHubPullRequestService):
    """Production work-item reader with pagination, budgets, and fork awareness."""

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
            return {
                "ok": False,
                "status": "invalid",
                "error": "invalid_issue_number",
            }
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
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{issue_number}"
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
            *dict_errors(comments_pages.get("errors")),
            *dict_errors(events_pages.get("errors")),
        ]
        comments = [self._comment(item) for item in comments_pages["items"]]
        events: list[dict[str, Any]] = []
        for item in events_pages["items"]:
            label = as_dict(item.get("label"))
            rename = as_dict(item.get("rename"))
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
        milestone = as_dict(payload.get("milestone"))
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
            or collection_partial(comments_pages)
            or collection_partial(events_pages)
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
            "truncated": (
                bool(comments_pages["truncated"])
                or bool(events_pages["truncated"])
            ),
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
