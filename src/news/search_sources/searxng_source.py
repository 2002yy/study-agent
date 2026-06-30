"""Optional SearXNG search provider.

SearXNG is intentionally opt-in.  Public instances often disable JSON output,
so failures must be silent and the caller should fall back to existing RSS
providers.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from src.news.search_sources.base import SearchSourceResult
from src.news.url_normalizer import is_probable_article_page_url
from src.web.security import validate_service_endpoint


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


def _valid_base_url(base_url: str) -> bool:
    return validate_service_endpoint(
        base_url,
        allow_loopback=(
            _env_flag("SEARXNG_ALLOW_LOOPBACK")
            or _env_flag("SEARXNG_ALLOW_LOCAL")
        ),
        allow_private_network=_env_flag("SEARXNG_ALLOW_PRIVATE_NETWORK"),
    )


def build_searxng_search_url(
    query: str,
    base_url: str,
    max_results: int = 10,
    language: str = "zh-CN",
    categories: str = "news",
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
        "categories": categories.strip() or "news",
    }
    if max_results > 0:
        params["pageno"] = "1"

    return urljoin(base_url + "/", "search") + "?" + urlencode(params)


def _parse_searxng_results(payload: bytes, max_results: int) -> list[SearchSourceResult]:
    try:
        data = json.loads(payload.decode("utf-8", errors="ignore"))
    except Exception:
        return []

    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        return []

    def score_of(raw: object) -> float:
        if not isinstance(raw, dict):
            return 0.0
        try:
            return float(raw.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    results: list[SearchSourceResult] = []
    for raw in sorted(raw_results, key=score_of, reverse=True):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not title or not is_probable_article_page_url(url):
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
                thumbnail=str(raw.get("thumbnail") or "").strip(),
                img_src=str(raw.get("img_src") or "").strip(),
                favicon=str(raw.get("favicon") or "").strip(),
                score=score_of(raw),
            )
        )
        if len(results) >= max_results:
            break
    return results


def search_searxng(
    query: str,
    max_results: int = 10,
    timeout: float | None = None,
    base_url: str | None = None,
    categories: str | None = None,
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
        categories=categories or os.getenv("NEWS_SEARXNG_CATEGORIES", "news"),
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
    if timeout is None:
        try:
            timeout = max(
                1.0,
                min(float(os.getenv("NEWS_SOURCE_TIMEOUT_SECONDS", "8")), 30.0),
            )
        except ValueError:
            timeout = 8.0
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
