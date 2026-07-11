"""Safe, general-purpose web tools for model-directed research.

This gateway is intentionally separate from the news pipeline: news uses RSS
ranking and a ``news`` SearXNG category, while chat tools need general web
search and explicit page reads.
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from src.news.article_fetcher import fetch_article_read_result
from src.news.search_sources.searxng_source import search_searxng


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
    if parsed.scheme in {"http", "https"} and "duckduckgo.com" not in (parsed.hostname or ""):
        return url
    target = parse_qs(parsed.query).get("uddg", [""])[0]
    target = unquote(target)
    parsed_target = urlparse(target)
    return target if parsed_target.scheme in {"http", "https"} else ""


class GeneralWebGateway:
    """Expose bounded search and read operations to a model tool loop."""

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        normalized = query.strip()
        if not normalized:
            return []
        limit = max(1, min(max_results, 8))
        searx_results = search_searxng(
            normalized,
            max_results=limit,
            categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general"),
        )
        if searx_results:
            return [
                {
                    "title": str(item.get("title", "")),
                    "url": str(item.get("link") or item.get("resolved_link") or ""),
                    "snippet": str(item.get("search_excerpt") or item.get("summary") or ""),
                    "source": str(item.get("source") or "SearXNG"),
                }
                for item in searx_results[:limit]
                if item.get("title") and (item.get("link") or item.get("resolved_link"))
            ]
        if not _env_flag("WEB_ENABLE_DUCKDUCKGO", default=True):
            return []
        return self._search_duckduckgo(normalized, limit)

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, str]:
        result = fetch_article_read_result(
            url.strip(),
            timeout=10,
            max_chars=max(500, min(max_chars, 12_000)),
        )
        if not result.ok:
            return {
                "ok": "false",
                "url": result.requested_url,
                "error": result.reason or "page_read_failed",
            }
        return {
            "ok": "true",
            "url": result.final_url or result.requested_url,
            "method": result.method,
            "content": result.text,
        }

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
            {**item, "snippet": "", "source": "DuckDuckGo"}
            for item in parser.results[:limit]
        ]
