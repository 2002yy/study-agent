"""Reader backends for the news pipeline."""

from src.news.readers.base import ReaderResult
from src.news.readers.firecrawl_reader import (
    build_firecrawl_scrape_url,
    firecrawl_enabled,
    read_with_firecrawl,
)
from src.news.readers.jina_reader import build_jina_reader_url, read_with_jina_reader
from src.news.readers.local_reader import read_html_locally

__all__ = [
    "ReaderResult",
    "read_html_locally",
    "build_jina_reader_url",
    "read_with_jina_reader",
    "build_firecrawl_scrape_url",
    "firecrawl_enabled",
    "read_with_firecrawl",
]
