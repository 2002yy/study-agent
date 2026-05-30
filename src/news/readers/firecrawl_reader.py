"""Optional Firecrawl-compatible reader backend.

This backend is disabled unless explicitly enabled by the caller.  It is meant
for a self-hosted or trusted Firecrawl-compatible endpoint and should not change
the default local-first behavior.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from src.news.article_extractor import clean_article_text
from src.news.readers.base import ReaderResult
from src.news.url_normalizer import is_public_http_url


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def firecrawl_enabled() -> bool:
    return _env_flag("NEWS_ENABLE_FIRECRAWL_READER", default=False)


def firecrawl_base_url() -> str:
    return (os.getenv("FIRECRAWL_BASE_URL") or "").strip().rstrip("/")


def firecrawl_api_key() -> str:
    return (os.getenv("FIRECRAWL_API_KEY") or "").strip()


def build_firecrawl_scrape_url(base_url: str) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        return ""
    return urljoin(base_url + "/", "v1/scrape")


def _extract_firecrawl_text(data: dict) -> str:
    candidates = [
        data.get("markdown"),
        data.get("content"),
        data.get("text"),
    ]
    nested = data.get("data")
    if isinstance(nested, dict):
        candidates.extend(
            [
                nested.get("markdown"),
                nested.get("content"),
                nested.get("text"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def read_with_firecrawl(
    url: str,
    timeout: int = 12,
    max_chars: int = 5000,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ReaderResult:
    """Read a public URL through a Firecrawl-compatible /v1/scrape endpoint."""
    target_url = (url or "").strip()
    if not is_public_http_url(target_url):
        return ReaderResult(error="unsafe-or-empty-url")

    configured_base_url = (base_url or firecrawl_base_url()).strip().rstrip("/")
    if not configured_base_url:
        return ReaderResult(error="missing-firecrawl-base-url")

    scrape_url = build_firecrawl_scrape_url(configured_base_url)
    if not scrape_url:
        return ReaderResult(error="invalid-firecrawl-base-url")

    body = json.dumps(
        {
            "url": target_url,
            "formats": ["markdown"],
            "onlyMainContent": True,
        }
    ).encode("utf-8")

    headers = {
        "User-Agent": "StudyAgent/1.0",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    key = (api_key if api_key is not None else firecrawl_api_key()).strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    req = Request(scrape_url, data=body, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                return ReaderResult(error="non-json-firecrawl-response")
            payload = response.read(max_chars * 8)
        data = json.loads(payload.decode("utf-8", errors="ignore"))
        text = clean_article_text(_extract_firecrawl_text(data), max_chars=max_chars)
        if not text:
            return ReaderResult()
        return ReaderResult(text=text, method="firecrawl")
    except Exception as exc:
        return ReaderResult(error=str(exc))
