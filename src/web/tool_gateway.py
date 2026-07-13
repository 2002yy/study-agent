"""Safe, general-purpose web tools for model-directed research.

This gateway is intentionally separate from the news pipeline: news uses RSS
ranking and a ``news`` SearXNG category, while chat and durable research need
general web search, explicit page reads, and bounded GitHub repository access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import os
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from src.news.article_fetcher import fetch_article_read_result
from src.news.search_sources.searxng_source import (
    get_last_searxng_error,
    search_searxng,
    searxng_enabled,
)
from src.web.github_reader import GitHubSourceReader
from src.web.github_snapshot import GitHubRepositorySnapshotter
from src.web.query_normalizer import normalize_web_query


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class _DuckDuckGoResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._href = ""
        self._parts: list[str] = []
        self._capturing = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        css_class = values.get("class") or ""
        if "result__a" not in css_class and "result-link" not in css_class:
            return
        self._href = values.get("href") or ""
        self._parts = []
        self._capturing = True

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capturing:
            return
        title = " ".join("".join(self._parts).split())
        url = _unwrap_duckduckgo_url(self._href)
        if title and url:
            self.results.append({"title": title, "url": url})
        self._capturing = False


def _unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and "duckduckgo.com" not in (
        parsed.hostname or ""
    ):
        return url
    target = parse_qs(parsed.query).get("uddg", [""])[0]
    target = unquote(target)
    parsed_target = urlparse(target)
    return target if parsed_target.scheme in {"http", "https"} else ""


def _result_key(item: dict[str, str]) -> str:
    return (item.get("url") or item.get("title") or "").strip().casefold()


def _dedupe_results(items: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        key = _result_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _snapshot_search_results(
    snapshot: dict[str, Any],
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in snapshot.get("files", [])[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "name": str(item.get("path") or "").rsplit("/", 1)[-1],
                "path": str(item.get("path") or ""),
                "sha": str(item.get("sha") or ""),
                "url": str(item.get("url") or ""),
                "repository": str(snapshot.get("repository") or ""),
                "score": int(item.get("score") or 0),
            }
        )
    return results


class GeneralWebGateway:
    """Expose bounded search, page reading, and GitHub browsing to model tools."""

    def __init__(
        self,
        github_reader: GitHubSourceReader | None = None,
        github_snapshotter: GitHubRepositorySnapshotter | None = None,
    ) -> None:
        self.github_reader = github_reader or GitHubSourceReader()
        self.github_snapshotter = github_snapshotter or GitHubRepositorySnapshotter()

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        """Compatibility list API used by older callers."""

        payload = self.search_detailed(query, max_results=max_results)
        return list(payload["results"])

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Search one already-planned query without creating more variants."""

        focused = " ".join(str(query or "").split())
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        limit = max(1, min(max_results, 12))
        if not focused:
            return {
                "status": "invalid_query",
                "reason": "empty_query",
                "query": focused,
                "results": [],
                "provider_errors": [],
                "searched_at": current.isoformat(),
            }

        results = self._search_single(focused, limit)
        provider_errors: list[str] = []
        error = get_last_searxng_error()
        if error:
            provider_errors.append(error)
        providers_enabled = searxng_enabled() or _env_flag(
            "WEB_ENABLE_DUCKDUCKGO", default=True
        )
        if results:
            status = "ok"
            reason = "results_found"
        elif not providers_enabled:
            status = "unavailable"
            reason = "no_search_provider_enabled"
        else:
            status = "empty"
            reason = "providers_returned_no_results"
        return {
            "status": status,
            "reason": reason,
            "query": focused,
            "results": results,
            "provider_errors": provider_errors,
            "searched_at": current.isoformat(),
        }

    def search_detailed(
        self,
        query: str,
        *,
        max_results: int = 5,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalization = normalize_web_query(query, now=now)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        limit = max(1, min(max_results, 12))
        if not normalization.raw_query:
            return {
                **normalization.to_dict(),
                "status": "invalid_query",
                "reason": "empty_query",
                "attempted_queries": [],
                "results": [],
                "provider_errors": [],
                "searched_at": current.isoformat(),
            }

        attempted: list[str] = []
        provider_errors: list[str] = []
        results: list[dict[str, str]] = []
        saw_available_provider = False
        for variant in normalization.query_variants:
            attempted.append(variant)
            exact = self.search_exact(variant, max_results=limit, now=current)
            if exact["status"] != "unavailable":
                saw_available_provider = True
            for error in exact.get("provider_errors", []):
                if error and error not in provider_errors:
                    provider_errors.append(str(error))
            results = _dedupe_results(
                [*results, *list(exact.get("results", []))],
                limit,
            )
            if results:
                break

        if results:
            status = "ok"
            reason = "results_found"
        elif not saw_available_provider:
            status = "unavailable"
            reason = "no_search_provider_enabled"
        else:
            status = "empty"
            reason = "providers_returned_no_results"
        return {
            **normalization.to_dict(),
            "status": status,
            "reason": reason,
            "attempted_queries": attempted,
            "results": results,
            "provider_errors": provider_errors,
            "searched_at": current.isoformat(),
        }

    def _search_single(self, query: str, limit: int) -> list[dict[str, str]]:
        searx_results = search_searxng(
            query,
            max_results=limit,
            categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general"),
        )
        if searx_results:
            return [
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("link") or item.get("resolved_link") or ""),
                    "snippet": str(
                        item.get("search_excerpt") or item.get("summary") or ""
                    ),
                    "source": str(item.get("source") or "SearXNG"),
                    "published_at": str(item.get("published_at") or ""),
                }
                for item in searx_results[:limit]
                if item.get("title")
                and (item.get("link") or item.get("resolved_link"))
            ]
        if not _env_flag("WEB_ENABLE_DUCKDUCKGO", default=True):
            return []
        return self._search_duckduckgo(query, limit)

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        value = str(url or "").strip()
        if self.github_reader.supports(value):
            return self.github_reader.read(value, max_chars=max_chars)
        result = fetch_article_read_result(
            value,
            timeout=10,
            max_chars=max(500, min(max_chars, 20_000)),
        )
        if not result.ok:
            return {
                "ok": False,
                "url": result.requested_url,
                "error": result.reason or "page_read_failed",
            }
        return {
            "ok": True,
            "kind": "web_page",
            "url": result.final_url or result.requested_url,
            "method": result.method,
            "content": result.text,
        }

    def github_search(
        self,
        repo_url: str,
        query: str,
        *,
        max_results: int = 8,
    ) -> dict[str, Any]:
        result = self.github_reader.search_repository(
            repo_url,
            query,
            max_results=max_results,
        )
        if result.get("ok") is not False:
            return result

        snapshot = self.github_snapshotter.snapshot(
            repo_url,
            query=query,
        )
        if snapshot.get("ok") is not True:
            return result
        return {
            "ok": True,
            "repository": str(snapshot.get("repository") or ""),
            "query": " ".join(str(query or "").split()),
            "mode": "snapshot_fallback",
            "default_branch": str(snapshot.get("default_branch") or ""),
            "results": _snapshot_search_results(
                snapshot,
                max_results=max(1, min(max_results, 20)),
            ),
            "truncated": bool(snapshot.get("tree_truncated")),
            "warning": (
                "github_search_failed; used bounded snapshot fallback: "
                f"{result.get('error', 'unknown_error')}"
            ),
        }

    def github_snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
    ) -> dict[str, Any]:
        return self.github_snapshotter.snapshot(
            repo_url,
            query=query,
            ref=ref,
        )

    @staticmethod
    def _search_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
        request = Request(
            "https://html.duckduckgo.com/html/?" + urlencode({"q": query}),
            headers={"User-Agent": "StudyAgent/1.0 (+general-web-tool)"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read(500_000).decode("utf-8", errors="ignore")
        except Exception:
            return []
        parser = _DuckDuckGoResultsParser()
        parser.feed(payload)
        return [
            {**item, "snippet": "", "source": "DuckDuckGo", "published_at": ""}
            for item in parser.results[:limit]
        ]
