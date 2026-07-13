"""Bounded GitHub repository and source-code reader.

The reader only talks to GitHub-owned hosts. Public repositories work without a
token; ``GITHUB_TOKEN`` or ``GH_TOKEN`` may be supplied for private repositories,
higher rate limits, and GitHub code search.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import json
import os
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

_GITHUB_API = "https://api.github.com"
_GITHUB_HOSTS = {"github.com", "www.github.com", "raw.githubusercontent.com", "api.github.com"}
_TEXT_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".dart", ".go", ".gradle", ".h", ".hpp",
    ".html", ".java", ".js", ".json", ".jsx", ".kt", ".kts", ".lua", ".md",
    ".mjs", ".php", ".py", ".rb", ".rs", ".scss", ".sh", ".sql", ".swift",
    ".toml", ".ts", ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml",
}
_QUERY_TOKEN = re.compile(r"[A-Za-z0-9_.-]+|[\u3400-\u9fff]+")


@dataclass(frozen=True)
class GitHubTarget:
    owner: str
    repo: str
    kind: str = "repository"
    ref: str = ""
    path: str = ""
    url: str = ""

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_repo(value: str) -> str:
    return value[:-4] if value.endswith(".git") else value


def parse_github_url(url: str) -> GitHubTarget | None:
    """Parse supported GitHub repository, directory, file, raw, or API URLs."""

    value = str(url or "").strip()
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host not in _GITHUB_HOSTS:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]

    if host == "raw.githubusercontent.com":
        if len(segments) < 4:
            return None
        return GitHubTarget(
            owner=segments[0],
            repo=_clean_repo(segments[1]),
            kind="file",
            ref=segments[2],
            path="/".join(segments[3:]),
            url=value,
        )

    if host == "api.github.com":
        if len(segments) < 3 or segments[0] != "repos":
            return None
        owner, repo = segments[1], _clean_repo(segments[2])
        if len(segments) >= 5 and segments[3] == "contents":
            return GitHubTarget(
                owner=owner,
                repo=repo,
                kind="content",
                ref=parse_qs(parsed.query).get("ref", [""])[0],
                path="/".join(segments[4:]),
                url=value,
            )
        return GitHubTarget(owner=owner, repo=repo, url=value)

    if len(segments) < 2:
        return None
    owner, repo = segments[0], _clean_repo(segments[1])
    if len(segments) >= 4 and segments[2] in {"blob", "tree"}:
        ref = parse_qs(parsed.query).get("ref", [segments[3]])[0]
        path = "/".join(segments[4:])
        return GitHubTarget(
            owner=owner,
            repo=repo,
            kind="file" if segments[2] == "blob" else "directory",
            ref=ref,
            path=path,
            url=value,
        )
    return GitHubTarget(owner=owner, repo=repo, url=value)


def _token() -> str:
    return (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()


def _headers(*, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "StudyAgent/1.0 (+github-source-reader)",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request_bytes(url: str, *, timeout: int, max_bytes: int, accept: str) -> bytes:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in {"api.github.com", "raw.githubusercontent.com"}:
        raise ValueError("unsupported_github_host")
    request = Request(url, headers=_headers(accept=accept))
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        return payload[:max_bytes]
    return payload


def _request_json(url: str, *, timeout: int = 10, max_bytes: int = 4_000_000) -> Any:
    payload = _request_bytes(
        url,
        timeout=timeout,
        max_bytes=max_bytes,
        accept="application/vnd.github+json",
    )
    return json.loads(payload.decode("utf-8", errors="replace"))


def _request_text(url: str, *, timeout: int = 10, max_bytes: int = 1_000_000) -> str:
    payload = _request_bytes(
        url,
        timeout=timeout,
        max_bytes=max_bytes,
        accept="text/plain, application/octet-stream;q=0.9, */*;q=0.1",
    )
    return payload.decode("utf-8", errors="replace")


def _api(path: str, **params: str | int) -> str:
    suffix = "?" + urlencode(params) if params else ""
    return f"{_GITHUB_API}{path}{suffix}"


def _decode_content(payload: dict[str, Any]) -> str:
    raw = str(payload.get("content") or "")
    if raw and str(payload.get("encoding") or "").lower() == "base64":
        try:
            return base64.b64decode(raw, validate=False).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return raw


def _entry(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(payload.get("name") or ""),
        "path": str(payload.get("path") or ""),
        "type": str(payload.get("type") or ""),
        "size": int(payload.get("size") or 0),
        "sha": str(payload.get("sha") or ""),
        "url": str(payload.get("html_url") or ""),
        "download_url": str(payload.get("download_url") or ""),
    }


def _query_tokens(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(token.casefold() for token in _QUERY_TOKEN.findall(query or "") if token))


def _text_path(path: str) -> bool:
    lowered = path.casefold()
    if any(lowered.endswith(extension) for extension in _TEXT_EXTENSIONS):
        return True
    return lowered.rsplit("/", 1)[-1] in {
        "dockerfile", "makefile", "package.json", "pyproject.toml", "cargo.toml",
        "go.mod", "requirements.txt", "readme", "license",
    }


class GitHubSourceReader:
    """Read and search bounded GitHub repository content."""

    def supports(self, url: str) -> bool:
        return parse_github_url(url) is not None

    def read(self, url: str, *, max_chars: int = 12_000, max_entries: int = 200) -> dict[str, Any]:
        target = parse_github_url(url)
        if target is None:
            return {"ok": False, "error": "unsupported_github_url", "url": str(url or "")}
        max_chars = max(500, min(int(max_chars), 30_000))
        max_entries = max(1, min(int(max_entries), 500))
        try:
            if (urlparse(target.url).hostname or "").lower() == "raw.githubusercontent.com":
                content = _request_text(target.url, max_bytes=max_chars * 4, timeout=10)
                return self._file_result(target, content, max_chars=max_chars, method="github_raw")
            if target.kind in {"file", "content"} and target.path:
                return self._read_file(target, max_chars=max_chars)
            if target.kind == "directory":
                return self._read_directory(target, max_entries=max_entries)
            return self._read_repository(target, max_chars=max_chars, max_entries=max_entries)
        except HTTPError as exc:
            return {
                "ok": False,
                "kind": target.kind,
                "repository": target.repository,
                "url": target.url,
                "error": f"github_http_{exc.code}",
            }
        except Exception as exc:
            return {
                "ok": False,
                "kind": target.kind,
                "repository": target.repository,
                "url": target.url,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def search_repository(
        self,
        repo_url: str,
        query: str,
        *,
        max_results: int = 8,
    ) -> dict[str, Any]:
        target = parse_github_url(repo_url)
        if target is None:
            return {"ok": False, "error": "unsupported_github_url", "results": []}
        focused = " ".join(str(query or "").split())
        if not focused:
            return {"ok": False, "error": "empty_query", "results": []}
        limit = max(1, min(int(max_results), 20))
        try:
            metadata = self._repository_metadata(target)
            default_branch = str(metadata.get("default_branch") or "main")
            if _token():
                searched = self._search_code_api(target, focused, limit=limit)
                if searched:
                    return {
                        "ok": True,
                        "repository": target.repository,
                        "query": focused,
                        "mode": "github_code_search",
                        "default_branch": default_branch,
                        "results": searched,
                        "truncated": False,
                    }
            fallback = self._search_tree_paths(
                target,
                focused,
                ref=target.ref or default_branch,
                limit=limit,
            )
            return {
                "ok": True,
                "repository": target.repository,
                "query": focused,
                "mode": "tree_path_fallback",
                "default_branch": default_branch,
                "results": fallback[0],
                "truncated": fallback[1],
                "warning": "content_search_requires_github_token" if not _token() else "",
            }
        except HTTPError as exc:
            return {
                "ok": False,
                "repository": target.repository,
                "query": focused,
                "error": f"github_http_{exc.code}",
                "results": [],
            }
        except Exception as exc:
            return {
                "ok": False,
                "repository": target.repository,
                "query": focused,
                "error": f"{type(exc).__name__}: {exc}",
                "results": [],
            }

    def _repository_metadata(self, target: GitHubTarget) -> dict[str, Any]:
        return dict(_request_json(_api(f"/repos/{quote(target.owner)}/{quote(target.repo)}")))

    def _contents_url(self, target: GitHubTarget, path: str, *, ref: str = "") -> str:
        encoded_path = quote(path, safe="/")
        base = f"/repos/{quote(target.owner)}/{quote(target.repo)}/contents"
        if encoded_path:
            base += f"/{encoded_path}"
        return _api(base, **({"ref": ref} if ref else {}))

    def _read_file(self, target: GitHubTarget, *, max_chars: int) -> dict[str, Any]:
        payload = _request_json(self._contents_url(target, target.path, ref=target.ref))
        if not isinstance(payload, dict):
            return {"ok": False, "error": "github_file_response_invalid", **target.to_dict()}
        content = _decode_content(payload)
        if not content and payload.get("download_url"):
            content = _request_text(
                str(payload["download_url"]),
                max_bytes=max_chars * 4,
                timeout=10,
            )
        return self._file_result(
            target,
            content,
            max_chars=max_chars,
            method="github_contents_api",
            sha=str(payload.get("sha") or ""),
        )

    def _file_result(
        self,
        target: GitHubTarget,
        content: str,
        *,
        max_chars: int,
        method: str,
        sha: str = "",
    ) -> dict[str, Any]:
        return {
            "ok": bool(content),
            "kind": "file",
            "repository": target.repository,
            "ref": target.ref,
            "path": target.path,
            "url": target.url,
            "method": method,
            "sha": sha,
            "content": content[:max_chars],
            "truncated": len(content) > max_chars,
            "error": "" if content else "empty_or_binary_file",
        }

    def _read_directory(self, target: GitHubTarget, *, max_entries: int) -> dict[str, Any]:
        payload = _request_json(self._contents_url(target, target.path, ref=target.ref))
        if not isinstance(payload, list):
            return {"ok": False, "error": "github_directory_response_invalid", **target.to_dict()}
        entries = [_entry(dict(item)) for item in payload[:max_entries] if isinstance(item, dict)]
        return {
            "ok": True,
            "kind": "directory",
            "repository": target.repository,
            "ref": target.ref,
            "path": target.path,
            "url": target.url,
            "entries": entries,
            "truncated": len(payload) > max_entries,
        }

    def _read_repository(
        self,
        target: GitHubTarget,
        *,
        max_chars: int,
        max_entries: int,
    ) -> dict[str, Any]:
        metadata = self._repository_metadata(target)
        ref = target.ref or str(metadata.get("default_branch") or "main")
        root = _request_json(self._contents_url(target, "", ref=ref))
        entries = [_entry(dict(item)) for item in root[:max_entries]] if isinstance(root, list) else []
        readme = ""
        try:
            readme_payload = _request_json(
                _api(
                    f"/repos/{quote(target.owner)}/{quote(target.repo)}/readme",
                    ref=ref,
                )
            )
            if isinstance(readme_payload, dict):
                readme = _decode_content(readme_payload)
        except HTTPError as exc:
            if exc.code != 404:
                raise
        return {
            "ok": True,
            "kind": "repository",
            "repository": target.repository,
            "ref": ref,
            "url": target.url,
            "description": str(metadata.get("description") or ""),
            "language": str(metadata.get("language") or ""),
            "license": str((metadata.get("license") or {}).get("spdx_id") or "")
            if isinstance(metadata.get("license"), dict)
            else "",
            "default_branch": str(metadata.get("default_branch") or ""),
            "readme": readme[:max_chars],
            "readme_truncated": len(readme) > max_chars,
            "entries": entries,
            "entries_truncated": isinstance(root, list) and len(root) > max_entries,
        }

    def _search_code_api(
        self,
        target: GitHubTarget,
        query: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        payload = _request_json(
            _api(
                "/search/code",
                q=f"{query} repo:{target.repository}",
                per_page=limit,
            )
        )
        if not isinstance(payload, dict):
            return []
        return [
            {
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "sha": str(item.get("sha") or ""),
                "url": str(item.get("html_url") or ""),
                "repository": target.repository,
                "score": float(item.get("score") or 0.0),
            }
            for item in payload.get("items", [])[:limit]
            if isinstance(item, dict)
        ]

    def _search_tree_paths(
        self,
        target: GitHubTarget,
        query: str,
        *,
        ref: str,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        payload = _request_json(
            _api(
                f"/repos/{quote(target.owner)}/{quote(target.repo)}/git/trees/{quote(ref, safe='')}",
                recursive=1,
            ),
            max_bytes=8_000_000,
        )
        if not isinstance(payload, dict):
            return [], False
        tokens = _query_tokens(query)
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for item in payload.get("tree", []):
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = str(item.get("path") or "")
            if not path or not _text_path(path):
                continue
            lowered = path.casefold()
            filename = lowered.rsplit("/", 1)[-1]
            score = sum(4 if token in filename else 1 if token in lowered else 0 for token in tokens)
            if score <= 0:
                continue
            ranked.append((score, path, item))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        results = [
            {
                "name": path.rsplit("/", 1)[-1],
                "path": path,
                "sha": str(item.get("sha") or ""),
                "size": int(item.get("size") or 0),
                "url": f"https://github.com/{target.repository}/blob/{ref}/{path}",
                "repository": target.repository,
                "score": score,
            }
            for score, path, item in ranked[:limit]
        ]
        return results, bool(payload.get("truncated"))
