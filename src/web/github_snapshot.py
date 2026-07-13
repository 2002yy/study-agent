"""Bounded GitHub repository snapshots for cross-file source analysis.

A snapshot is not a local git checkout. It records one repository ref, obtains a
recursive tree, ranks text files against the current research query, and fetches
a bounded set of blobs. The result is deterministic and safe to place in a tool
trace or persist in a ResearchRun.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import os
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote

from src.web.github_reader import (
    GitHubTarget,
    _api,
    _request_json,
    _text_path,
    parse_github_url,
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]+")
_EXCLUDED_PARTS = {
    ".git",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "generated",
    "node_modules",
    "target",
    "vendor",
}
_LOW_VALUE_SUFFIXES = (
    ".lock",
    ".map",
    ".min.css",
    ".min.js",
    ".snap",
)
_PRIORITY_NAMES = {
    "readme.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "cargo.toml",
    "go.mod",
    "dockerfile",
    "makefile",
    "compose.yaml",
    "docker-compose.yml",
}
_SOURCE_DIRS = {
    "app",
    "backend",
    "cmd",
    "frontend",
    "lib",
    "server",
    "src",
    "tests",
}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class GitHubSnapshotBudget:
    max_files: int = 24
    max_file_chars: int = 12000
    max_total_chars: int = 120000
    max_tree_entries: int = 100000

    @classmethod
    def from_env(cls) -> "GitHubSnapshotBudget":
        return cls(
            max_files=_env_int(
                "GITHUB_SNAPSHOT_MAX_FILES", 24, minimum=1, maximum=100
            ),
            max_file_chars=_env_int(
                "GITHUB_SNAPSHOT_MAX_FILE_CHARS",
                12000,
                minimum=1000,
                maximum=50000,
            ),
            max_total_chars=_env_int(
                "GITHUB_SNAPSHOT_MAX_TOTAL_CHARS",
                120000,
                minimum=5000,
                maximum=500000,
            ),
            max_tree_entries=_env_int(
                "GITHUB_SNAPSHOT_MAX_TREE_ENTRIES",
                100000,
                minimum=1000,
                maximum=100000,
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class SnapshotCandidate:
    path: str
    sha: str
    size: int
    score: int


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token.casefold()
            for token in _TOKEN_PATTERN.findall(value or "")
            if token.strip()
        )
    )


def _is_excluded(path: str) -> bool:
    normalized = path.casefold()
    parts = {part.casefold() for part in PurePosixPath(path).parts}
    if parts & _EXCLUDED_PARTS:
        return True
    return normalized.endswith(_LOW_VALUE_SUFFIXES)


def _path_score(path: str, query_tokens: tuple[str, ...]) -> int:
    lowered = path.casefold()
    name = PurePosixPath(lowered).name
    parts = set(PurePosixPath(lowered).parts)
    score = 0
    if name in _PRIORITY_NAMES:
        score += 45
    if parts & _SOURCE_DIRS:
        score += 12
    if name.startswith("test_") or name.endswith((".test.ts", ".test.tsx", ".spec.ts")):
        score += 4
    for token in query_tokens:
        if token in name:
            score += 30
        elif token in lowered:
            score += 10
    depth = len(PurePosixPath(path).parts)
    score += max(0, 6 - depth)
    return score


def _decode_blob(payload: dict[str, Any]) -> str:
    if str(payload.get("encoding") or "").lower() != "base64":
        return str(payload.get("content") or "")
    raw = str(payload.get("content") or "")
    if not raw:
        return ""
    try:
        return base64.b64decode(raw, validate=False).decode(
            "utf-8", errors="replace"
        )
    except Exception:
        return ""


class GitHubRepositorySnapshotter:
    def snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
        budget: GitHubSnapshotBudget | None = None,
    ) -> dict[str, Any]:
        target = parse_github_url(repo_url)
        if target is None:
            return {
                "ok": False,
                "error": "unsupported_github_url",
                "url": str(repo_url or ""),
            }
        active_budget = budget or GitHubSnapshotBudget.from_env()
        try:
            metadata = dict(
                _request_json(
                    _api(f"/repos/{quote(target.owner)}/{quote(target.repo)}")
                )
            )
            active_ref = ref or target.ref or str(
                metadata.get("default_branch") or "main"
            )
            tree = _request_json(
                _api(
                    f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                    f"/git/trees/{quote(active_ref, safe='')}",
                    recursive=1,
                ),
                max_bytes=8_000_000,
            )
            if not isinstance(tree, dict):
                return {
                    "ok": False,
                    "repository": target.repository,
                    "ref": active_ref,
                    "error": "github_tree_response_invalid",
                }
            candidates = self._rank_candidates(
                list(tree.get("tree") or [])[: active_budget.max_tree_entries],
                query=query,
            )
            files, used_chars, failures = self._read_candidates(
                target,
                candidates,
                ref=active_ref,
                budget=active_budget,
            )
            return {
                "ok": bool(files),
                "kind": "github_snapshot",
                "repository": target.repository,
                "ref": active_ref,
                "query": " ".join(str(query or "").split()),
                "description": str(metadata.get("description") or ""),
                "language": str(metadata.get("language") or ""),
                "default_branch": str(metadata.get("default_branch") or ""),
                "tree_sha": str(tree.get("sha") or ""),
                "tree_truncated": bool(tree.get("truncated")),
                "candidate_count": len(candidates),
                "files": files,
                "file_count": len(files),
                "used_chars": used_chars,
                "read_failures": failures,
                "budget": active_budget.to_dict(),
                "error": "" if files else "no_text_source_selected",
            }
        except HTTPError as exc:
            return {
                "ok": False,
                "repository": target.repository,
                "error": f"github_http_{exc.code}",
            }
        except Exception as exc:
            return {
                "ok": False,
                "repository": target.repository,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def _rank_candidates(
        self,
        tree_entries: list[Any],
        *,
        query: str,
    ) -> list[SnapshotCandidate]:
        query_tokens = _tokens(query)
        candidates: list[SnapshotCandidate] = []
        for raw in tree_entries:
            if not isinstance(raw, dict) or raw.get("type") != "blob":
                continue
            path = str(raw.get("path") or "")
            if not path or not _text_path(path) or _is_excluded(path):
                continue
            size = int(raw.get("size") or 0)
            if size <= 0 or size > 2_000_000:
                continue
            score = _path_score(path, query_tokens)
            candidates.append(
                SnapshotCandidate(
                    path=path,
                    sha=str(raw.get("sha") or ""),
                    size=size,
                    score=score,
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.path))
        return candidates

    def _read_candidates(
        self,
        target: GitHubTarget,
        candidates: list[SnapshotCandidate],
        *,
        ref: str,
        budget: GitHubSnapshotBudget,
    ) -> tuple[list[dict[str, Any]], int, list[dict[str, str]]]:
        files: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        used_chars = 0
        display_ref = quote(ref, safe="/")
        for candidate in candidates:
            if len(files) >= budget.max_files:
                break
            remaining = budget.max_total_chars - used_chars
            if remaining <= 0:
                break
            try:
                payload = _request_json(
                    _api(
                        f"/repos/{quote(target.owner)}/{quote(target.repo)}"
                        f"/git/blobs/{quote(candidate.sha, safe='')}"
                    ),
                    max_bytes=min(4_000_000, candidate.size * 2 + 4096),
                )
                if not isinstance(payload, dict):
                    raise ValueError("github_blob_response_invalid")
                content = _decode_blob(payload)
                if not content.strip():
                    raise ValueError("empty_or_binary_blob")
                limit = min(budget.max_file_chars, remaining)
                excerpt = content[:limit]
                files.append(
                    {
                        "path": candidate.path,
                        "sha": candidate.sha,
                        "size": candidate.size,
                        "score": candidate.score,
                        "content": excerpt,
                        "truncated": len(content) > limit,
                        "url": (
                            f"https://github.com/{target.repository}/blob/"
                            f"{display_ref}/{quote(candidate.path, safe='/')}"
                        ),
                    }
                )
                used_chars += len(excerpt)
            except Exception as exc:
                failures.append(
                    {
                        "path": candidate.path,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return files, used_chars, failures
