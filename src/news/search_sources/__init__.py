"""Optional search providers for the news pipeline."""

from src.news.search_sources.base import SearchSourceResult
from src.news.search_sources.searxng_source import (
    build_searxng_search_url,
    search_searxng,
    searxng_base_url,
    searxng_enabled,
)

__all__ = [
    "SearchSourceResult",
    "build_searxng_search_url",
    "search_searxng",
    "searxng_base_url",
    "searxng_enabled",
]
