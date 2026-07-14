from __future__ import annotations

from typing import Any

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.github_research_cache_repository import (
    GitHubResearchCacheRepository,
)
from src.web.github_cache_policy import GitHubResearchCachePolicy
from src.web.github_cached_analysis import (
    CachedGitHubChangeImpactService,
    CachedGitHubPRReviewContextService,
)
from src.web.github_cached_work_items import PersistentGitHubWorkItemService
from src.web.github_history import GitHubHistoryService

REPO = "https://github.com/openai/example"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class FakeHistory:
    request_graphql = None

    def __init__(self) -> None:
        self.resolve_calls: list[tuple[str, str]] = []

    def resolve_ref(self, repo_url: str, ref: str = "") -> dict[str, Any]:
        self.resolve_calls.append((repo_url, ref))
        commit_sha = {
            "base": BASE_SHA,
            "head": HEAD_SHA,
            "main": HEAD_SHA,
        }.get(ref, ref if len(ref) == 40 else HEAD_SHA)
        return {
            "ok": True,
            "status": "resolved",
            "repository": "openai/example",
            "requested_ref": ref or "main",
            "resolved_type": "commit",
            "resolved_name": ref or "main",
            "commit_sha": commit_sha,
            "tree_sha": "tree-" + commit_sha[:8],
        }

    @staticmethod
    def patch_hunks(patch: str) -> list[dict[str, int]]:
        return GitHubHistoryService.patch_hunks(patch)


def _cache(tmp_path) -> GitHubResearchCacheRepository:
    return GitHubResearchCacheRepository(RuntimeDatabase(tmp_path / "runtime.db"))


def _policy(*, reuse_partial: bool = False) -> GitHubResearchCachePolicy:
    return GitHubResearchCachePolicy(
        complete_ttl_seconds=300,
        partial_ttl_seconds=30,
        context_ttl_seconds=180,
        log_ttl_seconds=60,
        reuse_partial=reuse_partial,
        schema_version=1,
    )


def _commit_payload(sha: str) -> dict[str, Any]:
    return {
        "sha": sha,
        "html_url": f"https://github.com/openai/example/commit/{sha}",
        "commit": {
            "message": "commit",
            "tree": {"sha": "tree-" + sha[:8]},
            "author": {"name": "Author", "email": "a@example.com", "date": "date"},
            "committer": {
                "name": "Committer",
                "email": "c@example.com",
                "date": "date",
            },
            "verification": {"verified": True, "reason": "valid"},
        },
        "parents": [],
        "stats": {"additions": 1, "deletions": 0, "total": 1},
        "author": {"login": "author"},
        "committer": {"login": "committer"},
    }


def _pr_payload() -> dict[str, Any]:
    return {
        "number": 7,
        "title": "Persistent cache",
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
            "label": "openai:feature",
            "sha": HEAD_SHA,
            "repo": {"full_name": "openai/example"},
        },
        "commits": 1,
        "changed_files": 0,
        "additions": 0,
        "deletions": 0,
    }


def test_pull_request_cache_survives_service_restart(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    provider_calls: list[str] = []

    def provider(url: str, **_kwargs: Any) -> Any:
        provider_calls.append(url)
        if url.endswith("/repos/openai/example/pulls/7"):
            return _pr_payload()
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
        if url.endswith(f"/repos/openai/example/commits/{BASE_SHA}"):
            return _commit_payload(BASE_SHA)
        if url.endswith(f"/repos/openai/example/commits/{HEAD_SHA}"):
            return _commit_payload(HEAD_SHA)
        raise AssertionError(f"unexpected URL: {url}")

    cache = _cache(tmp_path)
    first = PersistentGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
        cache_repository=cache,
        cache_policy=_policy(),
    )
    first_result = first.pull_request(REPO, 7, include_checks=False)
    calls_after_first = len(provider_calls)

    second = PersistentGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not be called after restart")
        ),
        cache_repository=GitHubResearchCacheRepository(cache.database),
        cache_policy=_policy(),
    )
    second_result = second.pull_request(REPO, 7, include_checks=False)

    assert first_result["ok"] is True
    assert calls_after_first > 0
    assert len(provider_calls) == calls_after_first
    assert second_result["ok"] is True
    assert second_result["cache_hit"] is True
    assert second_result["cache_source"] == "sqlite"


def test_checks_cache_key_uses_resolved_commit_sha(tmp_path):
    provider_calls: list[str] = []

    def provider(url: str, **_kwargs: Any) -> Any:
        provider_calls.append(url)
        if f"/commits/{HEAD_SHA}/check-runs?" in url:
            return {"total_count": 0, "check_runs": []}
        if "/actions/runs?" in url:
            return {"total_count": 0, "workflow_runs": []}
        raise AssertionError(f"unexpected URL: {url}")

    cache = _cache(tmp_path)
    first = PersistentGitHubWorkItemService(
        FakeHistory(),  # type: ignore[arg-type]
        request_json=provider,
        cache_repository=cache,
        cache_policy=_policy(),
    )
    first_result = first.checks(REPO, ref="main", include_jobs=False)
    calls_after_first = len(provider_calls)

    second_history = FakeHistory()
    second = PersistentGitHubWorkItemService(
        second_history,  # type: ignore[arg-type]
        request_json=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not be called for immutable cache hit")
        ),
        cache_repository=GitHubResearchCacheRepository(cache.database),
        cache_policy=_policy(),
    )
    second_result = second.checks(REPO, ref="main", include_jobs=False)

    assert first_result["resolved_ref"] == HEAD_SHA
    assert len(provider_calls) == calls_after_first
    assert second_result["cache_hit"] is True
    assert second_result["commit_sha"] == HEAD_SHA
    assert second_history.resolve_calls == [(REPO, "main")]


class FakeChangeImpactDelegate:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    def analyze(
        self,
        repo_url: str,
        base: str,
        head: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append((repo_url, base, head, kwargs))
        return dict(self.result)


class FakeReviewContextDelegate:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[tuple[str, int, dict[str, Any]]] = []

    def build(self, repo_url: str, number: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((repo_url, number, kwargs))
        return dict(self.result)


def test_change_impact_cache_is_pinned_to_resolved_refs(tmp_path):
    cache = _cache(tmp_path)
    first_delegate = FakeChangeImpactDelegate(
        {"ok": True, "status": "resolved", "provider_status": "complete"}
    )
    first = CachedGitHubChangeImpactService(
        first_delegate,
        FakeHistory(),  # type: ignore[arg-type]
        cache,
        _policy(),
    )
    first.analyze(REPO, "base", "head")

    second_delegate = FakeChangeImpactDelegate(
        {"ok": False, "status": "failed", "error": "must not execute"}
    )
    second = CachedGitHubChangeImpactService(
        second_delegate,
        FakeHistory(),  # type: ignore[arg-type]
        GitHubResearchCacheRepository(cache.database),
        _policy(),
    )
    result = second.analyze(REPO, "base", "head")

    assert first_delegate.calls[0][1:3] == (BASE_SHA, HEAD_SHA)
    assert second_delegate.calls == []
    assert result["cache_hit"] is True
    assert result["requested_base"] == "base"
    assert result["requested_head"] == "head"


def test_review_context_cache_survives_restart(tmp_path):
    cache = _cache(tmp_path)
    first_delegate = FakeReviewContextDelegate(
        {"ok": True, "status": "resolved", "provider_status": "complete"}
    )
    first = CachedGitHubPRReviewContextService(first_delegate, cache, _policy())
    first.build(REPO, 7)

    second_delegate = FakeReviewContextDelegate(
        {"ok": False, "status": "failed", "error": "must not execute"}
    )
    second = CachedGitHubPRReviewContextService(
        second_delegate,
        GitHubResearchCacheRepository(cache.database),
        _policy(),
    )
    result = second.build(REPO, 7)

    assert second_delegate.calls == []
    assert result["cache_hit"] is True
    assert result["cache_source"] == "sqlite"


def test_partial_result_is_not_reused_by_default(tmp_path):
    cache = _cache(tmp_path)
    first_delegate = FakeReviewContextDelegate(
        {"ok": True, "status": "resolved", "provider_status": "partial"}
    )
    first = CachedGitHubPRReviewContextService(first_delegate, cache, _policy())
    first.build(REPO, 7)

    second_delegate = FakeReviewContextDelegate(
        {"ok": True, "status": "resolved", "provider_status": "complete"}
    )
    second = CachedGitHubPRReviewContextService(
        second_delegate,
        GitHubResearchCacheRepository(cache.database),
        _policy(),
    )
    result = second.build(REPO, 7)

    assert len(second_delegate.calls) == 1
    assert result.get("cache_hit") is not True
