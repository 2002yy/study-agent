"""Optional Jina Reader fallback backend.

This module is disabled unless the caller explicitly enables it.  It does not
use an API key and should not be part of the default local-first path.
"""

from __future__ import annotations

from urllib.parse import quote
from urllib.request import Request, urlopen

from src.news.article_extractor import clean_article_text
from src.news.readers.base import ReaderResult
from src.news.url_normalizer import is_public_http_url

JINA_READER_BASE_URL = "https://r.jina.ai/"


def build_jina_reader_url(url: str) -> str:
    """Build a safe Jina Reader URL for a public HTTP(S) target."""
    url = (url or "").strip()
    if not is_public_http_url(url):
        return ""
    return f"{JINA_READER_BASE_URL}{quote(url, safe=':/?&=%#,+') }"


def read_with_jina_reader(
    url: str,
    timeout: int = 8,
    max_chars: int = 5000,
) -> ReaderResult:
    """Read a URL through Jina Reader when explicitly enabled by caller."""
    reader_url = build_jina_reader_url(url)
    if not reader_url:
        return ReaderResult(error="unsafe-or-empty-url")

    req = Request(
        reader_url,
        headers={
            "User-Agent": "StudyAgent/1.0",
            "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            "X-Timeout": str(timeout),
            "X-Return-Format": "markdown",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as response:
            payload = response.read(max_chars * 6)
            content_type = response.headers.get("Content-Type", "")
        encoding = "utf-8"
        if "charset=" in content_type.lower():
            encoding = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
        text = payload.decode(encoding or "utf-8", errors="ignore")
        cleaned = clean_article_text(text, max_chars=max_chars)
        if not cleaned:
            return ReaderResult()
        return ReaderResult(text=cleaned, method="jina_reader")
    except Exception as exc:
        return ReaderResult(error=str(exc))
