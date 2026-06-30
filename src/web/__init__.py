"""Shared web-search primitives used by news and future research providers."""

from src.web.concurrency import BoundedOutcome, BoundedTask, run_bounded
from src.web.models import Evidence, ReadResult, SearchResult, parse_published_at
from src.web.orchestrator import WebSearchPlan, build_search_plan
from src.web.query_router import SearchIntent, route_query
from src.web.security import validate_service_endpoint

__all__ = [
    "BoundedOutcome",
    "BoundedTask",
    "Evidence",
    "ReadResult",
    "SearchResult",
    "SearchIntent",
    "WebSearchPlan",
    "build_search_plan",
    "parse_published_at",
    "run_bounded",
    "route_query",
    "validate_service_endpoint",
]
