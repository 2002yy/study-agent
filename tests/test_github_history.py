from __future__ import annotations

from urllib.error import HTTPError

import src.web.github_history as github_history
from src.web.github_history import GitHubHistoryService


REPO = "https://github.com/openai/example"
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40
TREE_A = "1" * 40
TREE_B = "2" * 40


def _not_found(url: str) -> HTTPError:
    return HTTPError(url, 404, "not found", None, None)


def _commit(sha: str, tree_sha: str, message: str = "change") -> dict:
    return {
        "sha": sha,
        "html_url": f"https://github.com/openai/example/commit/{sha}",
        "commit": {
            "message": message,
            "tree": {"sha": tree_sha},
            "author": {"name": "Author", "email": "a@example.com", "date": "2026-07-13T00:00:00Z"},
            "committer": {"name": "Committer", "email": "c@example.com", "date": "2026-07-13T00:01:00Z"},
            "verification": {"verified": True, "reason": "valid", "signature": "sig", "payload": "payload"},
        },
        "author": {"login": "author"},
        "committer": {"login": "committer"},
        "parents": [{"sha": "0" * 40}],
        "stats": {"additions": 2, "deletions": 1, "total": 3},
        "files": [],
    }


def _base_fake(url: str, **_kwargs):
    if url.endswith("/repos/openai/example"):
        return {"default_branch": "main"}
    if "/git/ref/heads/main" in url:
        return {"object": {"type": "commit", "sha": COMMIT_A}}
    if "/git/ref/tags/main" in url:
        raise _not_found(url)
    if url.endswith(f"/commits/{COMMIT_A}") or url.endswith("/commits/main"):
        return _commit(COMMIT_A, TREE_A)
    raise AssertionError(f"unexpected URL: {url}")


def test_default_branch_resolves_to_immutable_commit(monkeypatch):
    monkeypatch.setattr(github_history, "_request_json", _base_fake)
    service = GitHubHistoryService()

    result = service.resolve_ref(REPO)

    assert result["ok"] is True
    assert result["requested_ref"] == "main"
    assert result["resolved_type"] == "default_branch"
    assert result["commit_sha"] == COMMIT_A
    assert result["tree_sha"] == TREE_A


def test_branch_and_tag_same_name_with_different_commits_is_ambiguous(monkeypatch):
    def fake(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {"default_branch": "main"}
        if "/git/ref/heads/release" in url:
            return {"object": {"type": "commit", "sha": COMMIT_A}}
        if "/git/ref/tags/release" in url:
            return {"object": {"type": "commit", "sha": COMMIT_B}}
        if url.endswith("/commits/release"):
            return _commit(COMMIT_A, TREE_A)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_history, "_request_json", fake)
    result = GitHubHistoryService().resolve_ref(REPO, "release")

    assert result["ok"] is False
    assert result["status"] == "ambiguous"
    assert {item["type"] for item in result["candidates"]} == {"branch", "tag"}


def test_annotated_tag_is_peeled_to_commit(monkeypatch):
    tag_object = "c" * 40

    def fake(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {"default_branch": "main"}
        if "/git/ref/heads/v1.0.0" in url:
            raise _not_found(url)
        if "/git/ref/tags/v1.0.0" in url:
            return {"object": {"type": "tag", "sha": tag_object}}
        if url.endswith(f"/git/tags/{tag_object}"):
            return {"object": {"type": "commit", "sha": COMMIT_B}}
        if url.endswith("/commits/v1.0.0") or url.endswith(f"/commits/{COMMIT_B}"):
            return _commit(COMMIT_B, TREE_B)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_history, "_request_json", fake)
    result = GitHubHistoryService().resolve_ref(REPO, "v1.0.0")

    assert result["ok"] is True
    assert result["resolved_type"] == "tag"
    assert result["commit_sha"] == COMMIT_B
    assert result["tree_sha"] == TREE_B


def test_commit_returns_metadata_and_verification(monkeypatch):
    monkeypatch.setattr(github_history, "_request_json", _base_fake)
    result = GitHubHistoryService().commit(REPO, "main")

    assert result["commit_sha"] == COMMIT_A
    assert result["tree_sha"] == TREE_A
    assert result["parents"] == ["0" * 40]
    assert result["author"]["login"] == "author"
    assert result["committer"]["login"] == "committer"
    assert result["verification"]["verified"] is True


def test_compare_bounds_files_patch_and_parses_hunks(monkeypatch):
    def fake(url: str, **_kwargs):
        if url.endswith("/repos/openai/example"):
            return {"default_branch": "main"}
        if "/git/ref/heads/base" in url:
            return {"object": {"type": "commit", "sha": COMMIT_A}}
        if "/git/ref/tags/base" in url or "/git/ref/tags/head" in url:
            raise _not_found(url)
        if "/git/ref/heads/head" in url:
            return {"object": {"type": "commit", "sha": COMMIT_B}}
        if url.endswith("/commits/base") or url.endswith(f"/commits/{COMMIT_A}"):
            return _commit(COMMIT_A, TREE_A)
        if url.endswith("/commits/head") or url.endswith(f"/commits/{COMMIT_B}"):
            return _commit(COMMIT_B, TREE_B)
        if "/compare/" in url:
            return {
                "status": "ahead",
                "ahead_by": 2,
                "behind_by": 0,
                "total_commits": 2,
                "merge_base_commit": {"sha": COMMIT_A},
                "commits": [{"sha": COMMIT_B, "commit": {"message": "head"}, "html_url": "url"}],
                "files": [
                    {
                        "filename": "src/a.py",
                        "status": "modified",
                        "additions": 2,
                        "deletions": 1,
                        "changes": 3,
                        "sha": "file-a",
                        "patch": "@@ -10,2 +10,3 @@\n-old\n+new\n+more\n",
                    },
                    {
                        "filename": "src/b.py",
                        "status": "added",
                        "additions": 1,
                        "deletions": 0,
                        "changes": 1,
                        "sha": "file-b",
                        "patch": "@@ -0,0 +1 @@\n+x\n",
                    },
                ],
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(github_history, "_request_json", fake)
    result = GitHubHistoryService().compare(
        REPO,
        "base",
        "head",
        max_files=1,
        max_patch_chars=1000,
    )

    assert result["ok"] is True
    assert result["base"]["commit_sha"] == COMMIT_A
    assert result["head"]["commit_sha"] == COMMIT_B
    assert result["file_count"] == 1
    assert result["truncated"] is True
    assert result["files"][0]["hunks"] == [
        {"old_start": 10, "old_end": 11, "new_start": 10, "new_end": 12}
    ]


def test_blame_without_token_is_explicitly_unavailable(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    result = GitHubHistoryService().blame(REPO, "src/app.py", ref="main")

    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert result["error"] == "github_blame_requires_token"


def test_blame_clips_graphql_ranges_to_requested_lines(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(github_history, "_request_json", _base_fake)

    def graphql(_query: str, variables: dict):
        assert variables["expression"] == f"{COMMIT_A}:src/app.py"
        return {
            "data": {
                "repository": {
                    "object": {
                        "blame": {
                            "ranges": [
                                {
                                    "startingLine": 1,
                                    "endingLine": 20,
                                    "age": 1,
                                    "commit": {
                                        "oid": COMMIT_B,
                                        "messageHeadline": "origin",
                                        "committedDate": "2026-07-12T00:00:00Z",
                                        "url": "https://github.com/openai/example/commit/b",
                                        "author": {
                                            "name": "Author",
                                            "email": "a@example.com",
                                            "user": {"login": "author"},
                                        },
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }

    result = GitHubHistoryService(request_graphql=graphql).blame(
        REPO,
        "src/app.py",
        ref="main",
        start_line=5,
        end_line=8,
    )

    assert result["ok"] is True
    assert result["commit_sha"] == COMMIT_A
    assert result["ranges"][0]["start_line"] == 5
    assert result["ranges"][0]["end_line"] == 8
    assert result["ranges"][0]["commit_sha"] == COMMIT_B
    assert result["ranges"][0]["evidence"]["commit_sha"] == COMMIT_A
