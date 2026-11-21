"""Shared web-search primitives used by news and future research providers."""

from src.web.concurrency import BoundedOutcome, BoundedTask, run_bounded
from src.web.models import Evidence, ReadResult, SearchResult, parse_published_at
from src.web.security import validate_service_endpoint

__all__ = [
    "BoundedOutcome",
    "BoundedTask",
    "Evidence",
    "ReadResult",
    "SearchResult",
    "parse_published_at",
    "run_bounded",
    "validate_service_endpoint",
]
