"""Bounded GitHub pull request, issue, checks, and CI-log research.

The service is read-only. It pins mutable refs through ``GitHubHistoryService``,
keeps Provider failures explicit, bounds every collection, and redacts common
credential forms from workflow logs before returning them to a model or API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote

from src.repositories.provider_cache_repository import (
    ProviderCacheRepository,
    provider_cache_key,
)
from src.web.github_history import GitHubHistoryService
from src.web.github_reader import (
    GitHubTarget,
    _api,
    _request_json,
    _request_text,
    _token,
    parse_github_url,
)

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization:\s*(?:bearer|token)\s+)[^\s]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)([\"']?(?:token|api[_-]?key|secret)[\"']?\s*[:=]\s*[\"'])[^\"'\s]+"),
)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _http_error(exc: HTTPError) -> str:
    if exc.code == 404:
        return "not_found"
    if exc.code in {401, 403}:
        return "unavailable"
    if exc.code == 422:
        return "invalid"
    return f"github_http_{exc.code}"


def _actor(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    return {
        "login": str(item.get("login") or ""),
        "id": int(item.get("id") or 0),
        "type": str(item.get("type") or ""),
        "url": str(item.get("html_url") or ""),
    }


def _bounded_text(value: Any, *, max_chars: int = 8_000) -> tuple[str, bool]:
    text = str(value or "")
    limit = max(0, int(max_chars))
    return text[:limit], len(text) > limit


def _pagination_limit(limit: int) -> int:
    return max(1, min(int(limit) + 1, 100))


def _list_items(payload: Any, *, key: str = "") -> list[dict[str, Any]]:
    value = payload.get(key) if key and isinstance(payload, dict) else payload
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _provider_error(operation: str, error: str) -> dict[str, str]:
    return {"operation": operation, "error": error}


@dataclass(frozen=True)
class GitHubWorkItemBudget:
    max_files: int = 50
    max_patch_chars: int = 120_000
    max_comments: int = 100
    max_reviews: int = 100
    max_events: int = 100
    max_runs: int = 20
    max_checks: int = 100
    max_jobs: int = 100
    max_log_chars: int = 40_000
    max_log_lines: int = 400

    @classmethod
    def from_env(cls) -> "GitHubWorkItemBudget":
        return cls(
            max_files=_env_int("GITHUB_PR_MAX_FILES", 50, minimum=1, maximum=100),
            max_patch_chars=_env_int(
                "GITHUB_PR_MAX_PATCH_CHARS", 120_000, minimum=1_000, maximum=1_000_000
            ),
            max_comments=_env_int("GITHUB_ITEM_MAX_COMMENTS", 100, minimum=1, maximum=100),
            max_reviews=_env_int("GITHUB_PR_MAX_REVIEWS", 100, minimum=1, maximum=100),
            max_events=_env_int("GITHUB_ISSUE_MAX_EVENTS", 100, minimum=1, maximum=100),
            max_runs=_env_int("GITHUB_CHECKS_MAX_RUNS", 20, minimum=1, maximum=100),
            max_checks=_env_int("GITHUB_CHECKS_MAX_CHECKS", 100, minimum=1, maximum=100),
            max_jobs=_env_int("GITHUB_CHECKS_MAX_JOBS", 100, minimum=1, maximum=300),
            max_log_chars=_env_int(
                "GITHUB_CI_LOG_MAX_CHARS", 40_000, minimum=1_000, maximum=200_000
            ),
            max_log_lines=_env_int(
                "GITHUB_CI_LOG_MAX_LINES", 400, minimum=20, maximum=2_000
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class GitHubWorkItemService:
    """Read GitHub work items and CI evidence through bounded Provider calls."""

    def __init__(
        self,
        history_service: GitHubHistoryService | None = None,
        *,
        request_json: Callable[..., Any] | None = None,
        request_text: Callable[..., str] | None = None,
        request_graphql: Callable[[str, dict[str, Any]], Any] | None = None,
        cache_repository: ProviderCacheRepository | None = None,
    ) -> None:
        self.history_service = history_service or GitHubHistoryService()
        self.request_json = request_json or _request_json
        self.request_text = request_text or _request_text
        self.request_graphql = request_graphql or getattr(
            self.history_service, "request_graphql", None
        )
        self.cache_repository = cache_repository
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _persistent_cache_identity(key: str) -> tuple[str, str, str]:
        parts = key.split(":", 2)
        raw_kind = parts[0]
        kind = {
            "checks": "checks",
            "checks-v2": "checks",
            "pr": "work-item",
            "pr-v2": "work-item",
            "issue": "work-item",
            "issue-v2": "work-item",
            "ci-log": "ci-log",
        }.get(raw_kind, raw_kind)
        repository = parts[1].lower() if len(parts) > 1 else ""
        stable_key = provider_cache_key(
            kind=kind,
            repository=repository,
            request={"cache_scope": key},
        )
        return stable_key, kind, repository

    def _target(
        self, repo_url: str
    ) -> tuple[GitHubTarget | None, dict[str, Any] | None]:
        target = parse_github_url(repo_url)
        if target is None:
            return None, {
                "ok": False,
                "status": "invalid",
                "error": "unsupported_github_url",
                "url": str(repo_url or ""),
            }
        return target, None

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        ttl = _env_int(
            "GITHUB_WORK_ITEM_CACHE_TTL_SECONDS", 300, minimum=0, maximum=86_400
        )
        if ttl <= 0:
            return None
        item = self._cache.get(key)
        if item is not None and item[0] >= time.monotonic():
            return {**item[1], "cache_hit": True}
        if item is not None:
            self._cache.pop(key, None)
        if self.cache_repository is None:
            return None
        stable_key, kind, _ = self._persistent_cache_identity(key)
        # Checks are safe to reuse because their key is built only after the
        # requested ref has been resolved to a commit SHA. Moving work items
        # remain memory-only until their immutable refs are re-resolved.
        if kind != "checks":
            return None
        entry = self.cache_repository.get(stable_key)
        if entry is None:
            return None
        return {
            **entry.payload,
            "cache_hit": True,
            "cache_mode": "persistent",
            "cache_schema_version": entry.schema_version,
        }

    def _cache_put(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        ttl = _env_int(
            "GITHUB_WORK_ITEM_CACHE_TTL_SECONDS", 300, minimum=0, maximum=86_400
        )
        if ttl > 0 and value.get("status") not in {"unavailable", "failed"}:
            self._cache[key] = (time.monotonic() + ttl, dict(value))
            if self.cache_repository is not None:
                stable_key, kind, repository = self._persistent_cache_identity(key)
                commit_sha = str(value.get("commit_sha") or "")
                if kind == "checks" and re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
                    provider_status = str(value.get("provider_status") or "complete")
                    reuse_class = "partial" if provider_status == "partial" else "complete"
                    budget = value.get("provider_request_budget") or value.get("budget") or {}
                    self.cache_repository.put(
                        cache_key=stable_key,
                        kind=kind,
                        repository=repository,
                        payload=dict(value),
                        immutable_refs={"commit_sha": commit_sha.lower()},
                        provider_status=provider_status,
                        budget=budget if isinstance(budget, dict) else {},
                        reuse_class=reuse_class,
                        ttl_seconds=ttl,
                    )
        return {**value, "cache_hit": False}

    def _json(self, url: str, *, max_bytes: int = 8_000_000) -> Any:
        return self.request_json(url, max_bytes=max_bytes)

    def _text(self, url: str, *, max_bytes: int) -> str:
        return self.request_text(url, max_bytes=max_bytes)

    def _safe_json(
        self, operation: str, url: str, *, max_bytes: int = 8_000_000
    ) -> tuple[Any | None, dict[str, str] | None]:
        try:
            return self._json(url, max_bytes=max_bytes), None
        except HTTPError as exc:
            return None, _provider_error(operation, _http_error(exc))
        except Exception as exc:
            return None, _provider_error(operation, f"{type(exc).__name__}: {exc}")

    def _patch_file(
        self, item: dict[str, Any], *, patch_budget: int
    ) -> dict[str, Any]:
        patch = str(item.get("patch") or "")
        limit = max(0, int(patch_budget))
        excerpt = patch[:limit]
        return {
            "filename": str(item.get("filename") or ""),
            "previous_filename": str(item.get("previous_filename") or ""),
            "status": str(item.get("status") or ""),
            "additions": int(item.get("additions") or 0),
            "deletions": int(item.get("deletions") or 0),
            "changes": int(item.get("changes") or 0),
            "sha": str(item.get("sha") or ""),
            "blob_url": str(item.get("blob_url") or ""),
            "raw_url": str(item.get("raw_url") or ""),
            "contents_url": str(item.get("contents_url") or ""),
            "patch": excerpt,
            "patch_truncated": len(patch) > len(excerpt),
            "hunks": self.history_service.patch_hunks(excerpt),
        }

    @staticmethod
    def _review(item: dict[str, Any]) -> dict[str, Any]:
        body, truncated = _bounded_text(item.get("body"), max_chars=8_000)
        return {
            "id": int(item.get("id") or 0),
            "node_id": str(item.get("node_id") or ""),
            "state": str(item.get("state") or ""),
            "body": body,
            "body_truncated": truncated,
            "submitted_at": str(item.get("submitted_at") or ""),
            "commit_sha": str(item.get("commit_id") or ""),
            "author_association": str(item.get("author_association") or ""),
            "url": str(item.get("html_url") or ""),
            "user": _actor(item.get("user")),
        }

    @staticmethod
    def _comment(item: dict[str, Any], *, inline: bool = False) -> dict[str, Any]:
        body, truncated = _bounded_text(item.get("body"), max_chars=8_000)
        result: dict[str, Any] = {
            "id": int(item.get("id") or 0),
            "node_id": str(item.get("node_id") or ""),
            "body": body,
            "body_truncated": truncated,
            "created_at": str(item.get("created_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
            "author_association": str(item.get("author_association") or ""),
            "url": str(item.get("html_url") or ""),
            "user": _actor(item.get("user")),
        }
        if inline:
            result.update(
                {
                    "path": str(item.get("path") or ""),
                    "line": int(item.get("line") or 0),
                    "side": str(item.get("side") or ""),
                    "start_line": int(item.get("start_line") or 0),
                    "start_side": str(item.get("start_side") or ""),
                    "position": int(item.get("position") or 0),
                    "original_line": int(item.get("original_line") or 0),
                    "commit_sha": str(item.get("commit_id") or ""),
                    "original_commit_sha": str(item.get("original_commit_id") or ""),
                    "in_reply_to_id": int(item.get("in_reply_to_id") or 0),
                    "diff_hunk": _bounded_text(
                        item.get("diff_hunk"), max_chars=4_000
                    )[0],
                }
            )
        return result

    def _review_threads(
        self, target: GitHubTarget, number: int, *, limit: int
    ) -> dict[str, Any]:
        if not _token():
            return {
                "status": "unavailable",
                "error": "github_review_threads_require_token",
                "threads": [],
                "truncated": False,
            }
        if not callable(self.request_graphql):
            return {
                "status": "unavailable",
                "error": "github_graphql_adapter_unavailable",
                "threads": [],
                "truncated": False,
            }
        bounded = max(1, min(limit, 100))
        query = """
        query ReviewThreads($owner: String!, $repo: String!, $number: Int!, $first: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $number) {
              reviewThreads(first: $first) {
                totalCount
                nodes {
                  id isResolved isOutdated path line startLine diffSide
                  comments(first: 20) {
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
        try:
            payload = self.request_graphql(
                query,
                {
                    "owner": target.owner,
                    "repo": target.repo,
                    "number": number,
                    "first": bounded,
                },
            )
        except Exception as exc:
            return {
                "status": "unavailable",
                "error": f"{type(exc).__name__}: {exc}",
                "threads": [],
                "truncated": False,
            }
        if not isinstance(payload, dict) or payload.get("errors"):
            return {
                "status": "failed",
                "error": "github_review_threads_graphql_failed",
                "provider_errors": list(payload.get("errors") or [])
                if isinstance(payload, dict)
                else [],
                "threads": [],
                "truncated": False,
            }
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        repository = (
            data.get("repository") if isinstance(data.get("repository"), dict) else {}
        )
        pull = (
            repository.get("pullRequest")
            if isinstance(repository.get("pullRequest"), dict)
            else {}
        )
        raw = (
            pull.get("reviewThreads")
            if isinstance(pull.get("reviewThreads"), dict)
            else {}
        )
        nodes = _list_items(raw, key="nodes")[:bounded]
        threads: list[dict[str, Any]] = []
        for item in nodes:
            comments_data = (
                item.get("comments") if isinstance(item.get("comments"), dict) else {}
            )
            comments = []
            for comment in _list_items(comments_data, key="nodes"):
                body, body_truncated = _bounded_text(
                    comment.get("body"), max_chars=8_000
                )
                author = (
                    comment.get("author")
                    if isinstance(comment.get("author"), dict)
                    else {}
                )
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
                }
            )
        total = int(raw.get("totalCount") or len(threads))
        return {
            "status": "resolved",
            "error": "",
            "threads": threads,
            "thread_count": len(threads),
            "provider_thread_count": total,
            "unresolved_count": sum(not item["is_resolved"] for item in threads),
            "truncated": total > len(threads),
        }

    @staticmethod
    def _check_run(item: dict[str, Any]) -> dict[str, Any]:
        output = item.get("output") if isinstance(item.get("output"), dict) else {}
        summary, summary_truncated = _bounded_text(
            output.get("summary"), max_chars=6_000
        )
        text, text_truncated = _bounded_text(output.get("text"), max_chars=6_000)
        app = item.get("app") if isinstance(item.get("app"), dict) else {}
        return {
            "id": int(item.get("id") or 0),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "conclusion": str(item.get("conclusion") or ""),
            "started_at": str(item.get("started_at") or ""),
            "completed_at": str(item.get("completed_at") or ""),
            "details_url": str(item.get("details_url") or ""),
            "external_id": str(item.get("external_id") or ""),
            "app": {
                "id": int(app.get("id") or 0),
                "name": str(app.get("name") or ""),
                "slug": str(app.get("slug") or ""),
            },
            "output": {
                "title": str(output.get("title") or ""),
                "summary": summary,
                "summary_truncated": summary_truncated,
                "text": text,
                "text_truncated": text_truncated,
                "annotations_count": int(output.get("annotations_count") or 0),
            },
        }

    @staticmethod
    def _workflow_run(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(item.get("id") or 0),
            "name": str(item.get("name") or ""),
            "display_title": str(item.get("display_title") or ""),
            "event": str(item.get("event") or ""),
            "status": str(item.get("status") or ""),
            "conclusion": str(item.get("conclusion") or ""),
            "workflow_id": int(item.get("workflow_id") or 0),
            "run_number": int(item.get("run_number") or 0),
            "run_attempt": int(item.get("run_attempt") or 0),
            "head_branch": str(item.get("head_branch") or ""),
            "head_sha": str(item.get("head_sha") or ""),
            "created_at": str(item.get("created_at") or ""),
            "updated_at": str(item.get("updated_at") or ""),
            "run_started_at": str(item.get("run_started_at") or ""),
            "url": str(item.get("html_url") or ""),
            "jobs_url": str(item.get("jobs_url") or ""),
            "logs_url": str(item.get("logs_url") or ""),
            "artifacts_url": str(item.get("artifacts_url") or ""),
            "actor": _actor(item.get("actor")),
            "triggering_actor": _actor(item.get("triggering_actor")),
        }

    @staticmethod
    def _job(item: dict[str, Any]) -> dict[str, Any]:
        steps = []
        for raw in item.get("steps", []):
            if not isinstance(raw, dict):
                continue
            steps.append(
                {
                    "name": str(raw.get("name") or ""),
                    "number": int(raw.get("number") or 0),
                    "status": str(raw.get("status") or ""),
                    "conclusion": str(raw.get("conclusion") or ""),
                    "started_at": str(raw.get("started_at") or ""),
                    "completed_at": str(raw.get("completed_at") or ""),
                }
            )
        runner = item.get("runner_group_id")
        return {
            "id": int(item.get("id") or 0),
            "run_id": int(item.get("run_id") or 0),
            "name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "conclusion": str(item.get("conclusion") or ""),
            "started_at": str(item.get("started_at") or ""),
            "completed_at": str(item.get("completed_at") or ""),
            "head_sha": str(item.get("head_sha") or ""),
            "url": str(item.get("html_url") or ""),
            "runner_name": str(item.get("runner_name") or ""),
            "runner_group_id": int(runner or 0),
            "labels": [str(value) for value in item.get("labels", [])],
            "steps": steps,
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
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        resolved = self.history_service.resolve_ref(repo_url, ref)
        if resolved.get("ok") is not True:
            return resolved
        budget = GitHubWorkItemBudget.from_env()
        run_limit = max(1, min(int(max_runs or budget.max_runs), 100))
        check_limit = max(1, min(int(max_checks or budget.max_checks), 100))
        job_limit = max(1, min(int(max_jobs or budget.max_jobs), 300))
        commit_sha = str(resolved.get("commit_sha") or "")
        cache_key = (
            f"checks:{target.repository}:{commit_sha}:{run_limit}:{check_limit}:"
            f"{job_limit}:{int(include_jobs)}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        provider_errors: list[dict[str, str]] = []
        check_payload, error = self._safe_json(
            "check_runs",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/commits/{quote(commit_sha, safe='')}/check-runs",
                per_page=_pagination_limit(check_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_checks = _list_items(check_payload, key="check_runs")
        checks = [self._check_run(item) for item in raw_checks[:check_limit]]
        provider_check_count = (
            int(check_payload.get("total_count") or len(raw_checks))
            if isinstance(check_payload, dict)
            else 0
        )

        run_payload, error = self._safe_json(
            "workflow_runs",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}/actions/runs",
                head_sha=commit_sha,
                per_page=_pagination_limit(run_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_runs = _list_items(run_payload, key="workflow_runs")
        runs = [self._workflow_run(item) for item in raw_runs[:run_limit]]
        provider_run_count = (
            int(run_payload.get("total_count") or len(raw_runs))
            if isinstance(run_payload, dict)
            else 0
        )

        jobs: list[dict[str, Any]] = []
        jobs_truncated = False
        if include_jobs:
            remaining = job_limit
            for run in runs:
                if remaining <= 0:
                    jobs_truncated = True
                    break
                raw_id = int(run.get("id") or 0)
                if raw_id <= 0:
                    continue
                jobs_payload, error = self._safe_json(
                    f"workflow_jobs:{raw_id}",
                    _api(
                        f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                        f"/actions/runs/{raw_id}/jobs",
                        per_page=min(remaining + 1, 100),
                    ),
                )
                if error:
                    provider_errors.append(error)
                    continue
                raw_jobs = _list_items(jobs_payload, key="jobs")
                jobs.extend(self._job(item) for item in raw_jobs[:remaining])
                if len(raw_jobs) > remaining:
                    jobs_truncated = True
                remaining = job_limit - len(jobs)

        if check_payload is None and run_payload is None:
            result = {
                "ok": False,
                "status": "unavailable",
                "repository": target.repository,
                "requested_ref": str(resolved.get("requested_ref") or ""),
                "commit_sha": commit_sha,
                "error": "github_checks_providers_unavailable",
                "provider_errors": provider_errors,
            }
            return self._cache_put(cache_key, result)

        result = {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if provider_errors else "complete",
            "repository": target.repository,
            "requested_ref": str(resolved.get("requested_ref") or ""),
            "commit_sha": commit_sha,
            "tree_sha": str(resolved.get("tree_sha") or ""),
            "check_runs": checks,
            "check_count": len(checks),
            "provider_check_count": provider_check_count,
            "workflow_runs": runs,
            "workflow_run_count": len(runs),
            "provider_workflow_run_count": provider_run_count,
            "jobs": jobs,
            "job_count": len(jobs),
            "provider_errors": provider_errors,
            "truncated": (
                provider_check_count > len(checks)
                or provider_run_count > len(runs)
                or jobs_truncated
            ),
            "budget": {
                "max_runs": run_limit,
                "max_checks": check_limit,
                "max_jobs": job_limit,
                "include_jobs": include_jobs,
            },
        }
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
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        pr_number = int(number)
        if pr_number <= 0:
            return {"ok": False, "status": "invalid", "error": "invalid_pull_request_number"}
        budget = GitHubWorkItemBudget.from_env()
        file_limit = max(1, min(int(max_files or budget.max_files), 100))
        patch_limit = max(
            1_000, min(int(max_patch_chars or budget.max_patch_chars), 1_000_000)
        )
        comment_limit = max(1, min(int(max_comments or budget.max_comments), 100))
        review_limit = max(1, min(int(max_reviews or budget.max_reviews), 100))
        cache_key = (
            f"pr:{target.repository}:{pr_number}:{file_limit}:{patch_limit}:"
            f"{comment_limit}:{review_limit}:{int(include_checks)}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload, core_error = self._safe_json(
            "pull_request",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}/pulls/{pr_number}"
            ),
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
                },
            )

        provider_errors: list[dict[str, str]] = []
        base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
        head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
        base_sha = str(base.get("sha") or "")
        head_sha = str(head.get("sha") or "")

        files_payload, error = self._safe_json(
            "pull_request_files",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/pulls/{pr_number}/files",
                per_page=_pagination_limit(file_limit),
            ),
            max_bytes=12_000_000,
        )
        if error:
            provider_errors.append(error)
        raw_files = _list_items(files_payload)
        remaining_patch = patch_limit
        files: list[dict[str, Any]] = []
        for item in raw_files[:file_limit]:
            converted = self._patch_file(item, patch_budget=remaining_patch)
            remaining_patch -= len(str(converted.get("patch") or ""))
            files.append(converted)

        reviews_payload, error = self._safe_json(
            "pull_request_reviews",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/pulls/{pr_number}/reviews",
                per_page=_pagination_limit(review_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_reviews = _list_items(reviews_payload)
        reviews = [self._review(item) for item in raw_reviews[:review_limit]]

        inline_payload, error = self._safe_json(
            "pull_request_review_comments",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/pulls/{pr_number}/comments",
                per_page=_pagination_limit(comment_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_inline = _list_items(inline_payload)
        inline_comments = [
            self._comment(item, inline=True) for item in raw_inline[:comment_limit]
        ]

        issue_comments_payload, error = self._safe_json(
            "pull_request_issue_comments",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{pr_number}/comments",
                per_page=_pagination_limit(comment_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_issue_comments = _list_items(issue_comments_payload)
        issue_comments = [
            self._comment(item) for item in raw_issue_comments[:comment_limit]
        ]

        review_threads = self._review_threads(
            target, pr_number, limit=min(comment_limit, 100)
        )
        if review_threads.get("status") not in {"resolved", "unavailable"}:
            provider_errors.append(
                _provider_error(
                    "pull_request_review_threads",
                    str(review_threads.get("error") or "failed"),
                )
            )

        checks = (
            self.checks(
                repo_url,
                ref=head_sha,
                max_runs=budget.max_runs,
                max_checks=budget.max_checks,
                max_jobs=budget.max_jobs,
                include_jobs=True,
            )
            if include_checks and head_sha
            else {"status": "not_requested", "ok": False}
        )
        if include_checks and checks.get("ok") is not True:
            provider_errors.append(
                _provider_error(
                    "pull_request_checks", str(checks.get("error") or "unavailable")
                )
            )

        base_repo = base.get("repo") if isinstance(base.get("repo"), dict) else {}
        head_repo = head.get("repo") if isinstance(head.get("repo"), dict) else {}
        body, body_truncated = _bounded_text(payload.get("body"), max_chars=20_000)
        result = {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if provider_errors else "complete",
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
                "repository": str(base_repo.get("full_name") or ""),
                "commit": self.history_service.commit(repo_url, base_sha)
                if base_sha
                else {},
            },
            "head": {
                "ref": str(head.get("ref") or ""),
                "label": str(head.get("label") or ""),
                "commit_sha": head_sha,
                "repository": str(head_repo.get("full_name") or ""),
                "commit": self.history_service.commit(repo_url, head_sha)
                if head_sha
                else {},
            },
            "commits": int(payload.get("commits") or 0),
            "changed_files": int(payload.get("changed_files") or len(raw_files)),
            "additions": int(payload.get("additions") or 0),
            "deletions": int(payload.get("deletions") or 0),
            "files": files,
            "file_count": len(files),
            "reviews": reviews,
            "review_count": len(reviews),
            "inline_comments": inline_comments,
            "inline_comment_count": len(inline_comments),
            "issue_comments": issue_comments,
            "issue_comment_count": len(issue_comments),
            "review_threads": review_threads,
            "checks": checks,
            "provider_errors": provider_errors,
            "truncated": (
                len(raw_files) > file_limit
                or any(item.get("patch_truncated") for item in files)
                or len(raw_reviews) > review_limit
                or len(raw_inline) > comment_limit
                or len(raw_issue_comments) > comment_limit
                or bool(review_threads.get("truncated"))
                or bool(checks.get("truncated"))
            ),
            "budget": {
                "max_files": file_limit,
                "max_patch_chars": patch_limit,
                "max_comments": comment_limit,
                "max_reviews": review_limit,
                "include_checks": include_checks,
            },
        }
        return self._cache_put(cache_key, result)

    def issue(
        self,
        repo_url: str,
        number: int,
        *,
        max_comments: int | None = None,
        max_events: int | None = None,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        issue_number = int(number)
        if issue_number <= 0:
            return {"ok": False, "status": "invalid", "error": "invalid_issue_number"}
        budget = GitHubWorkItemBudget.from_env()
        comment_limit = max(1, min(int(max_comments or budget.max_comments), 100))
        event_limit = max(1, min(int(max_events or budget.max_events), 100))
        cache_key = f"issue:{target.repository}:{issue_number}:{comment_limit}:{event_limit}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        payload, core_error = self._safe_json(
            "issue",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}/issues/{issue_number}"
            ),
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
                },
            )

        provider_errors: list[dict[str, str]] = []
        comments_payload, error = self._safe_json(
            "issue_comments",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{issue_number}/comments",
                per_page=_pagination_limit(comment_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_comments = _list_items(comments_payload)
        comments = [self._comment(item) for item in raw_comments[:comment_limit]]

        events_payload, error = self._safe_json(
            "issue_events",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/issues/{issue_number}/events",
                per_page=_pagination_limit(event_limit),
            ),
        )
        if error:
            provider_errors.append(error)
        raw_events = _list_items(events_payload)
        events: list[dict[str, Any]] = []
        for item in raw_events[:event_limit]:
            label = item.get("label") if isinstance(item.get("label"), dict) else {}
            rename = item.get("rename") if isinstance(item.get("rename"), dict) else {}
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
        milestone = (
            payload.get("milestone")
            if isinstance(payload.get("milestone"), dict)
            else {}
        )
        linked_commit_shas = sorted(
            {
                str(item.get("commit_sha") or "")
                for item in events
                if item.get("commit_sha")
            }
        )
        result = {
            "ok": True,
            "status": "resolved",
            "provider_status": "partial" if provider_errors else "complete",
            "repository": target.repository,
            "number": issue_number,
            "kind": "pull_request" if isinstance(payload.get("pull_request"), dict) else "issue",
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
            "events": events,
            "event_count": len(events),
            "linked_commit_shas": linked_commit_shas,
            "provider_errors": provider_errors,
            "truncated": len(raw_comments) > comment_limit or len(raw_events) > event_limit,
            "budget": {
                "max_comments": comment_limit,
                "max_events": event_limit,
            },
        }
        return self._cache_put(cache_key, result)

    @staticmethod
    def _redact_log(text: str) -> str:
        sanitized_lines: list[str] = []
        for line in _ANSI.sub("", str(text or "").replace("\r\n", "\n")).splitlines():
            if "::add-mask::" in line:
                prefix = line.split("::add-mask::", 1)[0]
                sanitized_lines.append(f"{prefix}::add-mask::***")
                continue
            sanitized = line
            for pattern in _SECRET_PATTERNS:
                if pattern.groups:
                    sanitized = pattern.sub(r"\1***", sanitized)
                else:
                    sanitized = pattern.sub("***", sanitized)
            sanitized_lines.append(sanitized)
        return "\n".join(sanitized_lines)

    def ci_logs(
        self,
        repo_url: str,
        job_id: int,
        *,
        max_chars: int | None = None,
        max_lines: int | None = None,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        safe_job_id = int(job_id)
        if safe_job_id <= 0:
            return {"ok": False, "status": "invalid", "error": "invalid_workflow_job_id"}
        budget = GitHubWorkItemBudget.from_env()
        char_limit = max(
            1_000, min(int(max_chars or budget.max_log_chars), 200_000)
        )
        line_limit = max(20, min(int(max_lines or budget.max_log_lines), 2_000))
        cache_key = f"ci-log:{target.repository}:{safe_job_id}:{char_limit}:{line_limit}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        job_payload, job_error = self._safe_json(
            "workflow_job",
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/actions/jobs/{safe_job_id}"
            ),
        )
        if not isinstance(job_payload, dict):
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": job_error["error"] if job_error else "failed",
                    "repository": target.repository,
                    "job_id": safe_job_id,
                    "error": "github_workflow_job_unavailable",
                    "provider_errors": [job_error] if job_error else [],
                },
            )
        try:
            raw = self._text(
                _api(
                    f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                    f"/actions/jobs/{safe_job_id}/logs"
                ),
                max_bytes=max(char_limit * 8, 100_000),
            )
        except HTTPError as exc:
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": _http_error(exc),
                    "repository": target.repository,
                    "job_id": safe_job_id,
                    "error": f"github_http_{exc.code}",
                },
            )
        except Exception as exc:
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": "unavailable",
                    "repository": target.repository,
                    "job_id": safe_job_id,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

        sanitized = self._redact_log(raw)
        all_lines = sanitized.splitlines()
        selected_lines = all_lines[-line_limit:]
        excerpt = "\n".join(selected_lines)
        chars_truncated = len(excerpt) > char_limit
        if chars_truncated:
            excerpt = excerpt[-char_limit:]
        job = self._job(job_payload)
        result = {
            "ok": True,
            "status": "resolved",
            "repository": target.repository,
            "job_id": safe_job_id,
            "run_id": int(job.get("run_id") or 0),
            "head_sha": str(job.get("head_sha") or ""),
            "job": job,
            "log": excerpt,
            "line_count": len(selected_lines),
            "provider_line_count": len(all_lines),
            "truncated": len(all_lines) > line_limit or chars_truncated,
            "redacted": True,
            "budget": {"max_chars": char_limit, "max_lines": line_limit},
        }
        return self._cache_put(cache_key, result)
