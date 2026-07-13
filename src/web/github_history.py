"""Bounded GitHub ref, commit, compare, and blame research.

All operations are read-only and return structured uncertainty. Moving branch or
 tag names are resolved to immutable commit SHAs before source evidence is used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.web.github_reader import (
    GitHubTarget,
    _api,
    _headers,
    _request_json,
    _token,
    parse_github_url,
)

_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
_HUNK = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+"
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@"
)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _focused(value: str) -> str:
    return " ".join(str(value or "").split())


def _http_error(exc: HTTPError) -> str:
    if exc.code == 404:
        return "not_found"
    if exc.code in {401, 403}:
        return "unavailable"
    if exc.code == 422:
        return "invalid_ref"
    return f"github_http_{exc.code}"


def _safe_json(url: str) -> tuple[Any | None, str]:
    try:
        return _request_json(url), ""
    except HTTPError as exc:
        return None, _http_error(exc)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _request_graphql(query: str, variables: dict[str, Any], *, timeout: int = 15) -> Any:
    token = _token()
    if not token:
        raise ValueError("github_blame_requires_token")
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    headers = _headers()
    headers["Content-Type"] = "application/json"
    request = Request(
        "https://api.github.com/graphql",
        data=body,
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(4_000_001)
    if len(payload) > 4_000_000:
        raise ValueError("github_graphql_response_too_large")
    return json.loads(payload.decode("utf-8", errors="replace"))


@dataclass(frozen=True)
class ResolvedGitRef:
    status: str
    repository: str
    requested_ref: str
    resolved_type: str = ""
    resolved_name: str = ""
    commit_sha: str = ""
    tree_sha: str = ""
    candidates: tuple[dict[str, Any], ...] = ()
    aliases: tuple[str, ...] = ()
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "resolved" and bool(self.commit_sha)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "ok": self.ok,
            "candidates": [dict(item) for item in self.candidates],
            "aliases": list(self.aliases),
        }


class GitHubHistoryService:
    """Read Git history with bounded in-memory caching and explicit failures."""

    def __init__(
        self,
        *,
        request_json: Callable[..., Any] | None = None,
        request_graphql: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.request_json = request_json or _request_json
        self.request_graphql = request_graphql or _request_graphql
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _target(self, repo_url: str) -> tuple[GitHubTarget | None, dict[str, Any] | None]:
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
            "GITHUB_HISTORY_CACHE_TTL_SECONDS",
            300,
            minimum=0,
            maximum=86400,
        )
        if ttl <= 0:
            return None
        item = self._cache.get(key)
        if item is None or item[0] < time.monotonic():
            self._cache.pop(key, None)
            return None
        return {**item[1], "cache_hit": True}

    def _cache_put(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        ttl = _env_int(
            "GITHUB_HISTORY_CACHE_TTL_SECONDS",
            300,
            minimum=0,
            maximum=86400,
        )
        if ttl > 0 and value.get("status") not in {"unavailable", "failed"}:
            self._cache[key] = (time.monotonic() + ttl, dict(value))
        return {**value, "cache_hit": False}

    def _json(self, url: str, *, max_bytes: int = 4_000_000) -> Any:
        return self.request_json(url, max_bytes=max_bytes)

    def _repository_metadata(self, target: GitHubTarget) -> dict[str, Any]:
        payload = self._json(
            _api(f"/repos/{quote(target.owner)}/{quote(target.repo)}")
        )
        return dict(payload) if isinstance(payload, dict) else {}

    def _peel_tag(self, target: GitHubTarget, object_type: str, sha: str) -> tuple[str, str]:
        current_type = object_type
        current_sha = sha
        for _ in range(4):
            if current_type == "commit":
                return current_sha, ""
            if current_type != "tag" or not current_sha:
                return "", "tag_does_not_resolve_to_commit"
            payload = self._json(
                _api(
                    f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                    f"/git/tags/{quote(current_sha, safe='')}"
                )
            )
            if not isinstance(payload, dict):
                return "", "github_tag_response_invalid"
            obj = payload.get("object")
            if not isinstance(obj, dict):
                return "", "github_tag_object_missing"
            current_type = str(obj.get("type") or "")
            current_sha = str(obj.get("sha") or "")
        return "", "annotated_tag_depth_exceeded"

    def _ref_candidate(
        self,
        target: GitHubTarget,
        *,
        kind: str,
        name: str,
    ) -> tuple[dict[str, Any] | None, str]:
        path = quote(name, safe="/")
        payload, error = _safe_json(
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                f"/git/ref/{kind}/{path}"
            )
        )
        if payload is None:
            return None, error
        if not isinstance(payload, dict) or not isinstance(payload.get("object"), dict):
            return None, "github_ref_response_invalid"
        obj = dict(payload["object"])
        sha, peel_error = self._peel_tag(
            target,
            str(obj.get("type") or ""),
            str(obj.get("sha") or ""),
        )
        if peel_error:
            return None, peel_error
        return {
            "type": "branch" if kind == "heads" else "tag",
            "name": name,
            "commit_sha": sha,
            "object_sha": str(obj.get("sha") or ""),
            "object_type": str(obj.get("type") or ""),
        }, ""

    def _commit_payload(self, target: GitHubTarget, ref: str) -> tuple[dict[str, Any] | None, str]:
        try:
            payload = self._json(
                _api(
                    f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                    f"/commits/{quote(ref, safe='')}"
                )
            )
        except HTTPError as exc:
            return None, _http_error(exc)
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"
        return (dict(payload), "") if isinstance(payload, dict) else (None, "github_commit_response_invalid")

    def resolve_ref(self, repo_url: str, ref: str = "") -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        requested = _focused(ref or target.ref)
        cache_key = f"ref:{target.repository}:{requested or '<default>'}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            metadata = self._repository_metadata(target)
        except HTTPError as exc:
            return self._cache_put(
                cache_key,
                ResolvedGitRef(
                    status=_http_error(exc),
                    repository=target.repository,
                    requested_ref=requested,
                    error=f"github_http_{exc.code}",
                ).to_dict(),
            )
        except Exception as exc:
            return self._cache_put(
                cache_key,
                ResolvedGitRef(
                    status="unavailable",
                    repository=target.repository,
                    requested_ref=requested,
                    error=f"{type(exc).__name__}: {exc}",
                ).to_dict(),
            )
        default_branch = str(metadata.get("default_branch") or "main")
        active = requested or default_branch
        candidates: list[dict[str, Any]] = []
        errors: list[str] = []
        for kind in ("heads", "tags"):
            candidate, error = self._ref_candidate(target, kind=kind, name=active)
            if candidate is not None:
                candidates.append(candidate)
            elif error not in {"", "not_found"}:
                errors.append(error)
        commit_payload, commit_error = self._commit_payload(target, active)
        if commit_payload is not None:
            commit_sha = str(commit_payload.get("sha") or "")
            if commit_sha and not any(item["commit_sha"] == commit_sha for item in candidates):
                candidates.append(
                    {
                        "type": "commit",
                        "name": active,
                        "commit_sha": commit_sha,
                        "object_sha": commit_sha,
                        "object_type": "commit",
                    }
                )
        elif commit_error not in {"", "not_found"}:
            errors.append(commit_error)
        unique_shas = sorted({str(item.get("commit_sha") or "") for item in candidates if item.get("commit_sha")})
        if len(unique_shas) > 1:
            result = ResolvedGitRef(
                status="ambiguous",
                repository=target.repository,
                requested_ref=active,
                candidates=tuple(candidates),
                error="branch_tag_or_commit_ref_is_ambiguous",
            ).to_dict()
            return self._cache_put(cache_key, result)
        if not unique_shas:
            status = "unavailable" if errors else "not_found"
            result = ResolvedGitRef(
                status=status,
                repository=target.repository,
                requested_ref=active,
                candidates=tuple(candidates),
                error=errors[0] if errors else "github_ref_not_found",
            ).to_dict()
            return self._cache_put(cache_key, result)
        commit_sha = unique_shas[0]
        matching = [item for item in candidates if item.get("commit_sha") == commit_sha]
        type_priority = {"branch": 0, "tag": 1, "commit": 2}
        matching.sort(key=lambda item: type_priority.get(str(item.get("type")), 9))
        selected = matching[0]
        if not requested and str(selected.get("type")) == "branch":
            resolved_type = "default_branch"
        elif _SHA.match(active) and str(selected.get("type")) == "commit":
            resolved_type = "commit"
        else:
            resolved_type = str(selected.get("type") or "commit")
        tree_sha = ""
        if commit_payload is None or str(commit_payload.get("sha") or "") != commit_sha:
            commit_payload, _ = self._commit_payload(target, commit_sha)
        if isinstance(commit_payload, dict):
            commit_data = commit_payload.get("commit")
            if isinstance(commit_data, dict) and isinstance(commit_data.get("tree"), dict):
                tree_sha = str(commit_data["tree"].get("sha") or "")
        result = ResolvedGitRef(
            status="resolved",
            repository=target.repository,
            requested_ref=active,
            resolved_type=resolved_type,
            resolved_name=str(selected.get("name") or active),
            commit_sha=commit_sha,
            tree_sha=tree_sha,
            candidates=tuple(matching),
            aliases=tuple(sorted({str(item.get("type") or "") for item in matching})),
        ).to_dict()
        return self._cache_put(cache_key, result)

    def commit(self, repo_url: str, ref: str = "") -> dict[str, Any]:
        resolved = self.resolve_ref(repo_url, ref)
        if resolved.get("ok") is not True:
            return resolved
        target = parse_github_url(repo_url)
        assert target is not None
        commit_sha = str(resolved.get("commit_sha") or "")
        cache_key = f"commit:{target.repository}:{commit_sha}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        payload, error = self._commit_payload(target, commit_sha)
        if payload is None:
            return self._cache_put(
                cache_key,
                {
                    **resolved,
                    "ok": False,
                    "status": "unavailable" if error != "not_found" else "not_found",
                    "error": error or "github_commit_not_found",
                },
            )
        commit_data = payload.get("commit") if isinstance(payload.get("commit"), dict) else {}
        tree = commit_data.get("tree") if isinstance(commit_data.get("tree"), dict) else {}
        author = commit_data.get("author") if isinstance(commit_data.get("author"), dict) else {}
        committer = commit_data.get("committer") if isinstance(commit_data.get("committer"), dict) else {}
        verification = commit_data.get("verification") if isinstance(commit_data.get("verification"), dict) else {}
        result = {
            **resolved,
            "ok": True,
            "status": "resolved",
            "commit_sha": str(payload.get("sha") or commit_sha),
            "tree_sha": str(tree.get("sha") or resolved.get("tree_sha") or ""),
            "message": str(commit_data.get("message") or ""),
            "parents": [str(item.get("sha") or "") for item in payload.get("parents", []) if isinstance(item, dict)],
            "author": {
                "name": str(author.get("name") or ""),
                "email": str(author.get("email") or ""),
                "date": str(author.get("date") or ""),
                "login": str((payload.get("author") or {}).get("login") or "") if isinstance(payload.get("author"), dict) else "",
            },
            "committer": {
                "name": str(committer.get("name") or ""),
                "email": str(committer.get("email") or ""),
                "date": str(committer.get("date") or ""),
                "login": str((payload.get("committer") or {}).get("login") or "") if isinstance(payload.get("committer"), dict) else "",
            },
            "verification": {
                "verified": bool(verification.get("verified")),
                "reason": str(verification.get("reason") or ""),
                "signature": str(verification.get("signature") or ""),
                "payload": str(verification.get("payload") or ""),
            },
            "stats": dict(payload.get("stats") or {}) if isinstance(payload.get("stats"), dict) else {},
            "html_url": str(payload.get("html_url") or ""),
            "files": [
                self._compare_file(dict(item), patch_budget=20_000)
                for item in payload.get("files", [])[:100]
                if isinstance(item, dict)
            ],
        }
        return self._cache_put(cache_key, result)

    @staticmethod
    def patch_hunks(patch: str) -> list[dict[str, int]]:
        hunks: list[dict[str, int]] = []
        for line in str(patch or "").splitlines():
            match = _HUNK.match(line)
            if not match:
                continue
            old_start = int(match.group("old_start"))
            new_start = int(match.group("new_start"))
            old_count = int(match.group("old_count") or 1)
            new_count = int(match.group("new_count") or 1)
            hunks.append(
                {
                    "old_start": old_start,
                    "old_end": old_start + max(0, old_count - 1),
                    "new_start": new_start,
                    "new_end": new_start + max(0, new_count - 1),
                }
            )
        return hunks

    def _compare_file(self, item: dict[str, Any], *, patch_budget: int) -> dict[str, Any]:
        patch = str(item.get("patch") or "")
        excerpt = patch[: max(0, patch_budget)]
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
            "hunks": self.patch_hunks(excerpt),
        }

    def compare(
        self,
        repo_url: str,
        base: str,
        head: str,
        *,
        max_files: int | None = None,
        max_patch_chars: int | None = None,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        base_ref = self.resolve_ref(repo_url, base)
        head_ref = self.resolve_ref(repo_url, head)
        if base_ref.get("ok") is not True or head_ref.get("ok") is not True:
            return {
                "ok": False,
                "status": "unresolved_ref",
                "repository": target.repository,
                "base": base_ref,
                "head": head_ref,
                "error": "compare_requires_two_resolved_refs",
            }
        base_sha = str(base_ref.get("commit_sha") or "")
        head_sha = str(head_ref.get("commit_sha") or "")
        file_limit = max_files or _env_int("GITHUB_COMPARE_MAX_FILES", 100, minimum=1, maximum=300)
        patch_limit = max_patch_chars or _env_int(
            "GITHUB_COMPARE_MAX_PATCH_CHARS", 120_000, minimum=1_000, maximum=1_000_000
        )
        file_limit = max(1, min(int(file_limit), 300))
        patch_limit = max(1_000, min(int(patch_limit), 1_000_000))
        cache_key = f"compare:{target.repository}:{base_sha}:{head_sha}:{file_limit}:{patch_limit}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            payload = self._json(
                _api(
                    f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                    f"/compare/{quote(base_sha, safe='')}...{quote(head_sha, safe='')}"
                ),
                max_bytes=12_000_000,
            )
        except HTTPError as exc:
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": _http_error(exc),
                    "repository": target.repository,
                    "base": base_ref,
                    "head": head_ref,
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
                    "base": base_ref,
                    "head": head_ref,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        if not isinstance(payload, dict):
            return {"ok": False, "status": "failed", "error": "github_compare_response_invalid"}
        raw_files = [dict(item) for item in payload.get("files", []) if isinstance(item, dict)]
        remaining = patch_limit
        files: list[dict[str, Any]] = []
        for item in raw_files[:file_limit]:
            converted = self._compare_file(item, patch_budget=remaining)
            remaining -= len(str(converted.get("patch") or ""))
            files.append(converted)
            if remaining <= 0:
                break
        truncated = len(raw_files) > len(files) or any(item.get("patch_truncated") for item in files)
        result = {
            "ok": True,
            "status": str(payload.get("status") or "unknown"),
            "repository": target.repository,
            "base": base_ref,
            "head": head_ref,
            "merge_base_commit_sha": str((payload.get("merge_base_commit") or {}).get("sha") or "") if isinstance(payload.get("merge_base_commit"), dict) else "",
            "ahead_by": int(payload.get("ahead_by") or 0),
            "behind_by": int(payload.get("behind_by") or 0),
            "total_commits": int(payload.get("total_commits") or 0),
            "commits": [
                {
                    "sha": str(item.get("sha") or ""),
                    "message": str((item.get("commit") or {}).get("message") or "") if isinstance(item.get("commit"), dict) else "",
                    "html_url": str(item.get("html_url") or ""),
                }
                for item in payload.get("commits", [])[:100]
                if isinstance(item, dict)
            ],
            "files": files,
            "file_count": len(files),
            "provider_file_count": len(raw_files),
            "patch_chars": patch_limit - max(0, remaining),
            "truncated": truncated,
            "budget": {"max_files": file_limit, "max_patch_chars": patch_limit},
        }
        return self._cache_put(cache_key, result)

    def blame(
        self,
        repo_url: str,
        path: str,
        *,
        ref: str = "",
        start_line: int = 1,
        end_line: int = 0,
    ) -> dict[str, Any]:
        target, failure = self._target(repo_url)
        if failure is not None or target is None:
            return failure or {"ok": False, "status": "invalid"}
        normalized_path = str(path or "").strip().lstrip("/")
        if not normalized_path or ".." in normalized_path.split("/"):
            return {"ok": False, "status": "invalid", "error": "invalid_github_path"}
        if not _token():
            return {
                "ok": False,
                "status": "unavailable",
                "repository": target.repository,
                "path": normalized_path,
                "error": "github_blame_requires_token",
            }
        resolved = self.resolve_ref(repo_url, ref)
        if resolved.get("ok") is not True:
            return {**resolved, "path": normalized_path}
        line_limit = _env_int("GITHUB_BLAME_MAX_LINES", 500, minimum=1, maximum=2000)
        safe_start = max(1, int(start_line))
        safe_end = int(end_line) if int(end_line) > 0 else safe_start + line_limit - 1
        safe_end = min(max(safe_start, safe_end), safe_start + line_limit - 1)
        cache_key = (
            f"blame:{target.repository}:{resolved.get('commit_sha')}:{normalized_path}:"
            f"{safe_start}:{safe_end}"
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        query = """
        query Blame($owner: String!, $repo: String!, $expression: String!) {
          repository(owner: $owner, name: $repo) {
            object(expression: $expression) {
              ... on Blob {
                byteSize
                blame {
                  ranges {
                    startingLine
                    endingLine
                    age
                    commit {
                      oid
                      messageHeadline
                      committedDate
                      url
                      author { name email user { login } }
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
                    "expression": f"{resolved.get('commit_sha')}:{normalized_path}",
                },
            )
        except Exception as exc:
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": "unavailable",
                    "repository": target.repository,
                    "path": normalized_path,
                    "commit_sha": str(resolved.get("commit_sha") or ""),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        if not isinstance(payload, dict) or payload.get("errors"):
            return self._cache_put(
                cache_key,
                {
                    "ok": False,
                    "status": "failed",
                    "repository": target.repository,
                    "path": normalized_path,
                    "commit_sha": str(resolved.get("commit_sha") or ""),
                    "error": "github_blame_graphql_failed",
                    "provider_errors": list(payload.get("errors") or []) if isinstance(payload, dict) else [],
                },
            )
        repository = (payload.get("data") or {}).get("repository") if isinstance(payload.get("data"), dict) else None
        obj = repository.get("object") if isinstance(repository, dict) else None
        blame = obj.get("blame") if isinstance(obj, dict) else None
        raw_ranges = blame.get("ranges") if isinstance(blame, dict) else None
        if not isinstance(raw_ranges, list):
            return {
                "ok": False,
                "status": "not_found",
                "repository": target.repository,
                "path": normalized_path,
                "commit_sha": str(resolved.get("commit_sha") or ""),
                "error": "github_blame_not_available_for_path",
            }
        ranges = []
        for item in raw_ranges:
            if not isinstance(item, dict):
                continue
            item_start = int(item.get("startingLine") or 0)
            item_end = int(item.get("endingLine") or 0)
            clipped_start = max(safe_start, item_start)
            clipped_end = min(safe_end, item_end)
            if clipped_start > clipped_end:
                continue
            commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
            author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
            user = author.get("user") if isinstance(author.get("user"), dict) else {}
            ranges.append(
                {
                    "start_line": clipped_start,
                    "end_line": clipped_end,
                    "age": int(item.get("age") or 0),
                    "commit_sha": str(commit.get("oid") or ""),
                    "message": str(commit.get("messageHeadline") or ""),
                    "committed_at": str(commit.get("committedDate") or ""),
                    "url": str(commit.get("url") or ""),
                    "author": {
                        "name": str(author.get("name") or ""),
                        "email": str(author.get("email") or ""),
                        "login": str(user.get("login") or ""),
                    },
                    "evidence": {
                        "repository": target.repository,
                        "requested_ref": str(resolved.get("requested_ref") or ""),
                        "commit_sha": str(resolved.get("commit_sha") or ""),
                        "tree_sha": str(resolved.get("tree_sha") or ""),
                        "path": normalized_path,
                        "start_line": clipped_start,
                        "end_line": clipped_end,
                        "kind": "blame_range",
                    },
                }
            )
        result = {
            "ok": True,
            "status": "resolved",
            "repository": target.repository,
            "requested_ref": str(resolved.get("requested_ref") or ""),
            "commit_sha": str(resolved.get("commit_sha") or ""),
            "tree_sha": str(resolved.get("tree_sha") or ""),
            "path": normalized_path,
            "start_line": safe_start,
            "end_line": safe_end,
            "ranges": ranges,
            "range_count": len(ranges),
            "truncated": int(end_line or 0) > safe_end,
            "budget": {"max_lines": line_limit},
        }
        return self._cache_put(cache_key, result)
