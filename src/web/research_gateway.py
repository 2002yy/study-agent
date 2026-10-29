"""General-web adapter for durable research runs.

``WebLookupRun`` previously reused the news/RSS gateway, which made manual
research much narrower than the model-directed web tools. This adapter keeps the
existing service contract while delegating search and reading to the general
SearXNG/DuckDuckGo/GitHub-aware boundary.
"""

from __future__ import annotations

from typing import Any

from src.web.github_reader import parse_github_url
from src.web.tool_gateway import GeneralWebGateway, merge_trace


class ResearchSearchUnavailable(RuntimeError):
    """A search whose providers all failed.

    The trace travels on the exception because the caller still needs to know
    which providers were attempted; a gateway-level accessor would be shared
    state and could hand this search's evidence to a different run.
    """

    def __init__(self, message: str, *, trace: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.search_trace: dict[str, Any] = dict(trace or {})


class ResearchWebGateway:
    def __init__(self, gateway: GeneralWebGateway | None = None) -> None:
        self.gateway = gateway or GeneralWebGateway()
        self._warnings: list[dict[str, str]] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        """Compatibility list API used by callers that do not need evidence."""

        return self.search_with_trace(query, max_items=max_items)[0]

    def search_with_trace(
        self, query: str, *, max_items: int = 10
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search once and return the results with the trace of *that* search.

        Both values are produced by the same call on purpose. An accessor like
        ``search_trace()`` reads whatever the gateway stored last, so with one
        gateway shared by concurrent runs a search for one query could be
        recorded against another query's answer - the one evidence Quality-0
        cannot afford to get wrong.
        """

        direct_target = parse_github_url(query)
        if direct_target is not None:
            self._warnings = []
            label = direct_target.path or direct_target.repository
            return [self._direct_github_result(query, label)], {}

        result = self.gateway.search_exact(query, max_results=max_items)
        trace = merge_trace(result)
        self._warnings = [
            {
                "source": "general_web",
                "error_type": "provider_error",
                "message": str(error),
            }
            for error in result.get("provider_errors", [])
            if str(error).strip()
        ]
        status = str(result.get("status") or "")
        if status == "invalid_query":
            raise ValueError("Web lookup query is required")
        if status == "unavailable":
            raise ResearchSearchUnavailable(
                str(result.get("reason") or "web_search_unavailable"), trace=trace
            )

        normalized: list[dict[str, Any]] = []
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            record = dict(item)
            if record.get("url") and not record.get("link"):
                record["link"] = record["url"]
            if record.get("snippet") and not record.get("search_excerpt"):
                record["search_excerpt"] = record["snippet"]
            normalized.append(record)
        return normalized, trace

    @staticmethod
    def _direct_github_result(query: str, label: str) -> dict[str, Any]:
        excerpt = (
            "Direct GitHub repository, directory, or source file supplied by the user."
        )
        return {
            "title": f"GitHub source: {label}",
            "url": query,
            "link": query,
            "snippet": excerpt,
            "search_excerpt": excerpt,
            "source": "github.com",
            "source_type": "github_source",
            "published_at": "",
        }

    def read(
        self, url: str, *, max_chars: int = 6000, timeout: float | None = None
    ) -> dict[str, Any]:
        return self.gateway.read(url, max_chars=max_chars, timeout=timeout)

    def warnings(self) -> list[dict[str, str]]:
        return list(self._warnings)
