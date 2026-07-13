from __future__ import annotations

from urllib.error import HTTPError

from src.web.github_history import GitHubHistoryService
from src.web.github_work_items import GitHubWorkItemService


REPO = "https://github.com/openai/example"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class FakeHistory:
    request_graphql = None

    def resolve_ref(self, _repo_url: str, ref: str = "") -> dict:
        sha = HEAD_SHA if ref in {"", "main", "feature", HEAD_SHA} else BASE_SHA
        return {
            "ok": True,
            "status": "resolved",
            "repository": "openai/example",
            "requested_ref": ref or "main",
            "resolved_type": "commit",
            "resolved_name": ref or "main",
            "commit_sha": sha,
            "tree_sha": "tree-" + sha[:8],
        }

    def commit(self, _repo_url: str, ref: str = "") -> dict:
        return {
            "ok": True,
            "status": "resolved",
            "requested_ref": ref,
            "commit_sha": ref,
            "tree_sha": "tree-" + ref[:8],
            "message": "commit " + ref[:7],
        }

    @staticmethod
    def patch_hunks(patch: str) -> list[dict[str, int]]:
        return GitHubHistoryService.patch_hunks(patch)


def _not_found(url: str) -> HTTPError:
    return HTTPError(url, 404, "not found", None, None)


def _pr_provider(url: str, **_kwargs):
    if url.endswith("/repos/openai/example/pulls/7"):
        return {
            "number": 7,
            "title": "Improve history research",
            "body": "Body",
            "state": "open",
            "draft": False,
            "merged": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "created_at": "2026-07-13T00:00:00Z",
            "updated_at": "2026-07-13T01:00:00Z",
            "html_url": "https://github.com/openai/example/pull/7",
            "user": {"login": "author", "id": 1, "type": "User"},
            "author_association": "MEMBER",
            "requested_reviewers": [{"login": "reviewer", "id": 2}],
            "labels": [{"name": "feature"}],
            "base": {
                "ref": "main",
                "label": "openai:main",
                "sha": BASE_SHA,
                "repo": {"full_name": "openai/example"},
            },
            "head": {
                "ref": "feature",
                "label": "openai:feature",
                "sha": HEAD_SHA,
                "repo": {"full_name": "openai/example"},
            },
            "commits": 2,
            "changed_files": 2,
            "additions": 5,
            "deletions": 1,
        }
    if "/pulls/7/files" in url:
        return [
            {
                "filename": "src/a.py",
                "status": "modified",
                "additions": 3,
                "deletions": 1,
                "changes": 4,
                "sha": "file-a",
                "patch": "@@ -1,2 +1,3 @@\n-old\n+new\n+more\n",
            },
            {
                "filename": "tests/test_a.py",
                "status": "added",
                "additions": 2,
                "deletions": 0,
                "changes": 2,
                "sha": "file-test",
                "patch": "@@ -0,0 +1,2 @@\n+one\n+two\n",
            },
        ]
    if "/pulls/7/reviews" in url:
        return [
            {
                "id": 11,
                "node_id": "review-node",
                "state": "APPROVED",
                "body": "Looks good",
                "submitted_at": "2026-07-13T02:00:00Z",
                "commit_id": HEAD_SHA,
                "html_url": "https://github.com/openai/example/pull/7#review",
                "user": {"login": "reviewer", "id": 2},
            }
        ]
    if "/pulls/7/comments" in url:
        return [
            {
                "id": 12,
                "body": "Please rename this",
                "path": "src/a.py",
                "line": 2,
                "side": "RIGHT",
                "commit_id": HEAD_SHA,
                "html_url": "https://github.com/openai/example/pull/7#discussion",
                "user": {"login": "reviewer", "id": 2},
                "diff_hunk": "@@ -1 +1 @@",
            }
        ]
    if "/issues/7/comments" in url:
        return [
            {
                "id": 13,
                "body": "General note",
                "html_url": "https://github.com/openai/example/pull/7#issuecomment",
                "user": {"login": "author", "id": 1},
            }
        ]
    if f"/commits/{HEAD_SHA}/check-runs" in url:
        return {
            "total_count": 1,
            "check_runs": [
                {
                    "id": 21,
                    "name": "unit",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://github.com/openai/example/actions/runs/31",
                    "app": {"id": 1, "name": "Actions", "slug": "github-actions"},
                    "output": {"title": "Passed", "summary": "All good"},
                }
            ],
        }
    if "/actions/runs?" in url:
        return {
            "total_count": 1,
            "workflow_runs": [
                {
                    "id": 31,
                    "name": "CI",
                    "display_title": "feature",
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "success",
                    "workflow_id": 3,
                    "run_number": 9,
                    "run_attempt": 1,
                    "head_branch": "feature",
                    "head_sha": HEAD_SHA,
                    "html_url": "https://github.com/openai/example/actions/runs/31",
                }
            ],
        }
    if "/actions/runs/31/jobs" in url:
        return {
            "total_count": 1,
            "jobs": [
                {
                    "id": 41,
                    "run_id": 31,
                    "name": "test",
                    "status": "completed",
                    "conclusion": "success",
                    "head_sha": HEAD_SHA,
                    "html_url": "https://github.com/openai/example/actions/runs/31/job/41",
                    "labels": ["ubuntu-latest"],
                    "steps": [
                        {
                            "name": "pytest",
                            "number": 1,
                            "status": "completed",
                            "conclusion": "success",
                        }
                    ],
                }
            ],
        }
    raise AssertionError(f"unexpected URL: {url}")


def _threads(_query: str, variables: dict) -> dict:
    assert variables["number"] == 7
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "totalCount": 1,
                        "nodes": [
                            {
                                "id": "thread-1",
                                "isResolved": False,
                                "isOutdated": False,
                                "path": "src/a.py",
                                "line": 2,
                                "startLine": 2,
                                "diffSide": "RIGHT",
                                "comments": {
                                    "nodes": [
                                        {
                                            "databaseId": 12,
                                            "body": "Please rename this",
                                            "createdAt": "2026-07-13T02:00:00Z",
                                            "updatedAt": "2026-07-13T02:00:00Z",
                                            "url": "url",
                                            "author": {"login": "reviewer"},
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            }
        }
    }


def test_pull_request_combines_commits_files_reviews_threads_and_checks(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-" + "token")
    service = GitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=_pr_provider,
        request_graphql=_threads,
    )

    result = service.pull_request(
        REPO,
        7,
        max_files=1,
        max_patch_chars=1_000,
        max_comments=10,
        max_reviews=10,
        include_checks=True,
    )

    assert result["ok"] is True
    assert result["base"]["commit_sha"] == BASE_SHA
    assert result["head"]["commit_sha"] == HEAD_SHA
    assert result["head"]["commit"]["tree_sha"] == "tree-" + HEAD_SHA[:8]
    assert result["file_count"] == 1
    assert result["files"][0]["hunks"] == [
        {"old_start": 1, "old_end": 2, "new_start": 1, "new_end": 3}
    ]
    assert result["review_count"] == 1
    assert result["inline_comments"][0]["path"] == "src/a.py"
    assert result["review_threads"]["unresolved_count"] == 1
    assert result["checks"]["jobs"][0]["steps"][0]["name"] == "pytest"
    assert result["truncated"] is True


def test_issue_returns_comments_events_and_linked_commits():
    def provider(url: str, **_kwargs):
        if url.endswith("/repos/openai/example/issues/9"):
            return {
                "number": 9,
                "title": "Bug",
                "body": "Details",
                "state": "open",
                "state_reason": None,
                "locked": False,
                "html_url": "https://github.com/openai/example/issues/9",
                "user": {"login": "reporter", "id": 4},
                "assignees": [{"login": "owner", "id": 5}],
                "labels": [{"name": "bug"}],
                "milestone": {"number": 1, "title": "v1", "state": "open"},
            }
        if "/issues/9/comments" in url:
            return [{"id": 1, "body": "reproduced", "user": {"login": "owner"}}]
        if "/issues/9/events" in url:
            return [
                {
                    "id": 2,
                    "event": "referenced",
                    "commit_id": BASE_SHA,
                    "commit_url": "commit-url",
                    "actor": {"login": "owner"},
                }
            ]
        raise AssertionError(f"unexpected URL: {url}")

    result = GitHubWorkItemService(
        FakeHistory(), request_json=provider  # type: ignore[arg-type]
    ).issue(REPO, 9)

    assert result["ok"] is True
    assert result["kind"] == "issue"
    assert result["labels"] == ["bug"]
    assert result["comments"][0]["body"] == "reproduced"
    assert result["linked_commit_shas"] == [BASE_SHA]


def test_checks_returns_explicit_unavailable_when_both_providers_fail():
    def provider(url: str, **_kwargs):
        raise _not_found(url)

    result = GitHubWorkItemService(
        FakeHistory(), request_json=provider  # type: ignore[arg-type]
    ).checks(REPO, ref=HEAD_SHA)

    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert len(result["provider_errors"]) == 2


def test_ci_logs_redact_credentials_and_keep_bounded_tail():
    def provider(url: str, **_kwargs):
        assert url.endswith("/actions/jobs/41")
        return {
            "id": 41,
            "run_id": 31,
            "name": "test",
            "status": "completed",
            "conclusion": "failure",
            "head_sha": HEAD_SHA,
            "steps": [],
        }

    github_token = "gh" + "p_" + ("a1" * 16)
    api_token = "s" + "k-" + ("b2" * 12)
    raw_log = "\n".join(
        [
            *(f"old line {index}" for index in range(25)),
            f"Authorization: Bearer {github_token}",
            "::add-mask::" + "super-secret",
            f"api_key='{api_token}'",
            "failure: assertion mismatch",
        ]
    )
    service = GitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
        request_text=lambda _url, **_kwargs: raw_log,
    )

    result = service.ci_logs(REPO, 41, max_chars=2_000, max_lines=20)

    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["line_count"] == 20
    assert "old line 0" not in result["log"]
    assert "gh" + "p_" not in result["log"]
    assert "s" + "k-" not in result["log"]
    assert "super-secret" not in result["log"]
    assert "failure: assertion mismatch" in result["log"]
    assert result["redacted"] is True
