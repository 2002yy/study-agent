"""Optional SearXNG search provider.

SearXNG is intentionally opt-in.  Public instances often disable JSON output,
so failures must be silent and the caller should fall back to existing RSS
providers.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from src.news.search_sources.base import SearchSourceResult
from src.news.url_normalizer import is_public_http_url


_LAST_SEARXNG_ERROR = ""


def get_last_searxng_error() -> str:
    return _LAST_SEARXNG_ERROR


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def searxng_enabled() -> bool:
    return _env_flag("NEWS_ENABLE_SEARXNG", default=False)


def searxng_base_url() -> str:
    return (os.getenv("SEARXNG_BASE_URL") or "").strip().rstrip("/")


def _is_explicitly_allowed_local_searxng(base_url: str) -> bool:
    if not _env_flag("SEARXNG_ALLOW_LOCAL", default=False):
        return False

    try:
        parsed = urlparse(base_url)
    except Exception:
        return False

    if parsed.scheme.lower() not in {"http", "https"}:
        return False

    if parsed.username or parsed.password:
        return False

    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "::1", "localhost"}


def _valid_base_url(base_url: str) -> bool:
    return bool(
        base_url
        and (
            is_public_http_url(base_url)
            or _is_explicitly_allowed_local_searxng(base_url)
        )
    )


def build_searxng_search_url(
    query: str,
    base_url: str,
    max_results: int = 10,
    language: str = "zh-CN",
) -> str:
    """Build a SearXNG JSON search URL.

    SearXNG supports both `/` and `/search`; `/search` is clearer and easier to
    test.  JSON output may be disabled on many public instances.
    """
    query = (query or "").strip()
    base_url = (base_url or "").strip().rstrip("/")
    if not query or not _valid_base_url(base_url):
        return ""

    params = {
        "q": query,
        "format": "json",
        "language": language,
        "categories": "general",
    }
    if max_results > 0:
        params["pageno"] = "1"

    return urljoin(base_url + "/", "search") + "?" + urlencode(params)


def _parse_searxng_results(payload: bytes, max_results: int) -> list[SearchSourceResult]:
    try:
        data = json.loads(payload.decode("utf-8", errors="ignore"))
    except Exception:
        return []

    results: list[SearchSourceResult] = []
    for raw in data.get("results", []):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not title or not is_public_http_url(url):
            continue
        engine = raw.get("engine") or raw.get("engines") or "SearXNG"
        if isinstance(engine, list):
            engine = ", ".join(str(e) for e in engine[:3]) or "SearXNG"
        results.append(
            SearchSourceResult(
                title=title,
                url=url,
                source=f"SearXNG/{engine}",
                content=str(raw.get("content") or "").strip(),
                published_at=str(raw.get("publishedDate") or raw.get("published_at") or "").strip(),
            )
        )
        if len(results) >= max_results:
            break
    return results


def search_searxng(
    query: str,
    max_results: int = 10,
    timeout: int = 8,
    base_url: str | None = None,
) -> list[dict]:
    """Return normalized news items from SearXNG or [] on any failure."""
    global _LAST_SEARXNG_ERROR
    _LAST_SEARXNG_ERROR = ""

    if not searxng_enabled():
        return []

    configured_base_url = (base_url or searxng_base_url()).strip().rstrip("/")
    search_url = build_searxng_search_url(
        query,
        configured_base_url,
        max_results=max_results,
    )
    if not search_url:
        return []

    req = Request(
        search_url,
        headers={
            "User-Agent": "StudyAgent/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                _LAST_SEARXNG_ERROR = (
                    f"Unexpected Content-Type: {content_type!r}"
                )
                return []
            payload = response.read(500_000)
    except Exception as exc:
        _LAST_SEARXNG_ERROR = f"{type(exc).__name__}: {exc}"
        return []

    return [item.to_news_item() for item in _parse_searxng_results(payload, max_results)]
