from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from src.web.github_history import GitHubHistoryService
from src.web.github_paginated_work_items import PaginatedGitHubWorkItemService

REPO = "https://github.com/openai/example"
FORK_REPO = "https://github.com/contributor/example-fork"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class FakeHistory:
    request_graphql = None

    def resolve_ref(self, repo_url: str, ref: str = "") -> dict:
        return {
            "ok": True,
            "status": "resolved",
            "repository": repo_url.rsplit("/", 2)[-2]
            + "/"
            + repo_url.rsplit("/", 1)[-1],
            "requested_ref": ref or "main",
            "resolved_type": "commit",
            "resolved_name": ref or "main",
            "commit_sha": ref or HEAD_SHA,
            "tree_sha": "tree-" + (ref or HEAD_SHA)[:8],
        }

    @staticmethod
    def patch_hunks(patch: str) -> list[dict[str, int]]:
        return GitHubHistoryService.patch_hunks(patch)


def _page(url: str) -> int:
    return int(parse_qs(urlparse(url).query).get("page", ["1"])[0])


def _http_404(url: str) -> HTTPError:
    return HTTPError(url, 404, "not found", None, None)


def _commit_payload(sha: str) -> dict:
    return {
        "sha": sha,
        "html_url": f"https://github.com/example/commit/{sha}",
        "commit": {
            "message": "commit",
            "tree": {"sha": "tree-" + sha[:8]},
            "author": {
                "name": "Author",
                "email": "author@example.com",
                "date": "2026-07-14T00:00:00Z",
            },
            "committer": {
                "name": "Committer",
                "email": "committer@example.com",
                "date": "2026-07-14T00:00:00Z",
            },
            "verification": {"verified": True, "reason": "valid"},
        },
        "parents": [],
        "stats": {"additions": 1, "deletions": 0, "total": 1},
        "author": {"login": "author"},
        "committer": {"login": "committer"},
    }


def _pr_payload(*, cross_fork: bool = False) -> dict:
    return {
        "number": 7,
        "title": "Paginate provider evidence",
        "body": "Body",
        "state": "open",
        "draft": False,
        "merged": False,
        "mergeable": True,
        "mergeable_state": "clean",
        "html_url": "https://github.com/openai/example/pull/7",
        "user": {"login": "author", "id": 1, "type": "User"},
        "base": {
            "ref": "main",
            "label": "openai:main",
            "sha": BASE_SHA,
            "repo": {"full_name": "openai/example"},
        },
        "head": {
            "ref": "feature",
            "label": (
                "contributor:feature" if cross_fork else "openai:feature"
            ),
            "sha": HEAD_SHA,
            "repo": {
                "full_name": (
                    "contributor/example-fork" if cross_fork else "openai/example"
                )
            },
        },
        "commits": 2,
        "changed_files": 4,
        "additions": 8,
        "deletions": 2,
    }


def test_pull_request_paginates_rest_and_graphql_collections(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_PROVIDER_PAGE_SIZE", "2")
    provider_calls: list[str] = []

    def provider(url: str, **_kwargs):
        provider_calls.append(url)
        if url.endswith("/repos/openai/example/pulls/7"):
            return _pr_payload()
        if "/pulls/7/files?" in url:
            pages = {
                1: [
                    {"filename": "src/a.py", "patch": "@@ -1 +1 @@\n-a\n+b"},
                    {"filename": "src/b.py", "patch": "@@ -1 +1 @@\n-a\n+b"},
                ],
                2: [
                    {"filename": "src/c.py", "patch": "@@ -1 +1 @@\n-a\n+b"},
                    {"filename": "src/d.py", "patch": "@@ -1 +1 @@\n-a\n+b"},
                ],
            }
            return pages.get(_page(url), [])
        if any(
            marker in url
            for marker in (
                "/pulls/7/reviews?",
                "/pulls/7/comments?",
                "/issues/7/comments?",
            )
        ):
            return []
        if url.endswith(f"/repos/openai/example/commits/{BASE_SHA}"):
            return _commit_payload(BASE_SHA)
        if url.endswith(f"/repos/openai/example/commits/{HEAD_SHA}"):
            return _commit_payload(HEAD_SHA)
        raise AssertionError(f"unexpected URL: {url}")

    graphql_calls: list[dict] = []

    def graphql(_query: str, variables: dict) -> dict:
        graphql_calls.append(dict(variables))
        after = variables.get("after")
        node = {
            "id": "thread-1" if after is None else "thread-2",
            "isResolved": False,
            "isOutdated": False,
            "path": "src/a.py",
            "line": 1,
            "startLine": 1,
            "diffSide": "RIGHT",
            "comments": {
                "totalCount": 1,
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "databaseId": 10 if after is None else 11,
                        "body": "review",
                        "createdAt": "2026-07-14T00:00:00Z",
                        "updatedAt": "2026-07-14T00:00:00Z",
                        "url": "url",
                        "author": {"login": "reviewer"},
                    }
                ],
            },
        }
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "totalCount": 2,
                            "pageInfo": {
                                "hasNextPage": after is None,
                                "endCursor": "cursor-1" if after is None else None,
                            },
                            "nodes": [node],
                        }
                    }
                }
            }
        }

    result = PaginatedGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
        request_graphql=graphql,
    ).pull_request(
        REPO,
        7,
        max_files=3,
        max_comments=3,
        max_reviews=3,
        include_checks=False,
        max_provider_requests=12,
        max_pages_per_collection=4,
    )

    assert result["ok"] is True
    assert [item["filename"] for item in result["files"]] == [
        "src/a.py",
        "src/b.py",
        "src/c.py",
    ]
    assert result["pagination"]["files"]["pages_fetched"] == 2
    assert result["pagination"]["files"]["stop_reason"] == "item_budget_reached"
    assert result["review_threads"]["thread_count"] == 2
    assert result["review_threads"]["pagination"]["pages_fetched"] == 2
    assert graphql_calls[1]["after"] == "cursor-1"
    assert result["base"]["commit"]["commit_sha"] == BASE_SHA
    assert result["head"]["commit"]["commit_sha"] == HEAD_SHA
    assert result["provider_request_budget"]["used_requests"] == 10
    assert result["provider_request_budget"]["scope"] == (
        "pull_request_rest_graphql_calls"
    )
    assert len(provider_calls) == 8
    assert result["truncated"] is True


def test_pull_request_budget_exhaustion_keeps_partial_evidence(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls: list[str] = []

    def provider(url: str, **_kwargs):
        calls.append(url)
        if url.endswith("/repos/openai/example/pulls/7"):
            return _pr_payload()
        if "/pulls/7/files?" in url:
            return [{"filename": "src/a.py", "patch": "@@ -1 +1 @@\n-a\n+b"}]
        raise AssertionError("request budget should prevent later provider calls")

    result = PaginatedGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
    ).pull_request(
        REPO,
        7,
        include_checks=False,
        max_provider_requests=2,
        max_pages_per_collection=4,
    )

    assert result["ok"] is True
    assert result["provider_status"] == "partial"
    assert result["file_count"] == 1
    assert len(calls) == 2
    assert result["provider_request_budget"]["used_requests"] == 2
    assert result["provider_request_budget"]["exhausted_operations"] == [
        "pull_request_reviews",
        "pull_request_review_comments",
        "pull_request_issue_comments",
        "pull_request_base_commit:openai/example",
        "pull_request_head_commit:openai/example",
    ]
    assert result["pagination"]["reviews"]["stop_reason"] == (
        "request_budget_exhausted"
    )
    assert result["truncated"] is True


def test_cross_fork_pr_uses_source_repo_for_head_commit_and_check_fallback(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def provider(url: str, **_kwargs):
        if url.endswith("/repos/openai/example/pulls/7"):
            return _pr_payload(cross_fork=True)
        if any(
            marker in url
            for marker in (
                "/pulls/7/files?",
                "/pulls/7/reviews?",
                "/pulls/7/comments?",
                "/issues/7/comments?",
            )
        ):
            return []
        if url.startswith("https://api.github.com/repos/openai/example/") and (
            "/check-runs?" in url or "/actions/runs?" in url
        ):
            raise _http_404(url)
        if f"/repos/contributor/example-fork/commits/{HEAD_SHA}/check-runs?" in url:
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "id": 21,
                        "name": "fork-ci",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            }
        if "/repos/contributor/example-fork/actions/runs?" in url:
            return {"total_count": 0, "workflow_runs": []}
        if url.endswith(f"/repos/openai/example/commits/{BASE_SHA}"):
            return _commit_payload(BASE_SHA)
        if url.endswith(
            f"/repos/contributor/example-fork/commits/{HEAD_SHA}"
        ):
            return _commit_payload(HEAD_SHA)
        raise AssertionError(f"unexpected URL: {url}")

    result = PaginatedGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
    ).pull_request(
        REPO,
        7,
        include_checks=True,
        max_provider_requests=20,
    )

    assert result["ok"] is True
    assert result["cross_repository"] is True
    assert result["head"]["repository"] == "contributor/example-fork"
    assert result["head"]["repository_url"] == FORK_REPO
    assert result["head"]["is_cross_repository"] is True
    assert result["head"]["commit"]["repository"] == (
        "contributor/example-fork"
    )
    assert result["head"]["commit"]["commit_sha"] == HEAD_SHA
    assert result["checks"]["ok"] is True
    assert result["checks_repository"] == "contributor/example-fork"
    assert result["checks"]["fallback_from_repository"] == "openai/example"
    assert result["checks"]["check_runs"][0]["name"] == "fork-ci"


def test_checks_paginates_jobs_across_pages(monkeypatch):
    monkeypatch.setenv("GITHUB_PROVIDER_PAGE_SIZE", "2")

    def provider(url: str, **_kwargs):
        if f"/commits/{HEAD_SHA}/check-runs?" in url:
            return {"total_count": 0, "check_runs": []}
        if "/actions/runs?" in url:
            return {
                "total_count": 1,
                "workflow_runs": [{"id": 31, "name": "CI", "head_sha": HEAD_SHA}],
            }
        if "/actions/runs/31/jobs?" in url:
            pages = {
                1: {
                    "total_count": 4,
                    "jobs": [
                        {"id": 41, "run_id": 31, "name": "job-1"},
                        {"id": 42, "run_id": 31, "name": "job-2"},
                    ],
                },
                2: {
                    "total_count": 4,
                    "jobs": [
                        {"id": 43, "run_id": 31, "name": "job-3"},
                        {"id": 44, "run_id": 31, "name": "job-4"},
                    ],
                },
            }
            return pages[_page(url)]
        raise AssertionError(f"unexpected URL: {url}")

    result = PaginatedGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
    ).checks(
        REPO,
        ref=HEAD_SHA,
        max_runs=2,
        max_checks=2,
        max_jobs=3,
        max_provider_requests=8,
        max_pages_per_collection=4,
    )

    assert result["ok"] is True
    assert [item["name"] for item in result["jobs"]] == [
        "job-1",
        "job-2",
        "job-3",
    ]
    assert result["pagination"]["workflow_jobs"][0]["pages_fetched"] == 2
    assert result["pagination"]["workflow_jobs"][0]["truncated"] is True
    assert result["provider_request_budget"]["used_requests"] == 4
