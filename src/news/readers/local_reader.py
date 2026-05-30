"""Local article reader backend using installed extraction libraries."""

from __future__ import annotations

from src.news.article_extractor import extract_article_text
from src.news.readers.base import ReaderResult


def read_html_locally(
    html: str,
    url: str = "",
    max_chars: int = 5000,
) -> ReaderResult:
    """Extract readable text from HTML using local libraries only."""
    try:
        text, method = extract_article_text(html, url=url, max_chars=max_chars)
        if not text:
            return ReaderResult()
        return ReaderResult(text=text, method=f"local_{method}")
    except Exception as exc:
        return ReaderResult(error=str(exc))
