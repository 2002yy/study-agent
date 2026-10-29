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


class ResearchWebGateway:
    def __init__(self, gateway: GeneralWebGateway | None = None) -> None:
        self.gateway = gateway or GeneralWebGateway()
        self._warnings: list[dict[str, str]] = []
        self._last_trace: dict[str, Any] = {}

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        # Reset before anything else: a trace left over from the previous query
        # would be attached to this attempt, and evidence that describes a
        # different search is worse than no evidence.
        self._last_trace = {}
        direct_target = parse_github_url(query)
        if direct_target is not None:
            self._warnings = []
            label = direct_target.path or direct_target.repository
            return [
                {
                    "title": f"GitHub source: {label}",
                    "url": query,
                    "link": query,
                    "snippet": (
                        "Direct GitHub repository, directory, or source file supplied "
                        "by the user."
                    ),
                    "search_excerpt": (
                        "Direct GitHub repository, directory, or source file supplied "
                        "by the user."
                    ),
                    "source": "github.com",
                    "source_type": "github_source",
                    "published_at": "",
                }
            ]

        result = self.gateway.search_exact(query, max_results=max_items)
        # Kept before the status checks so a failing search still reports which
        # providers ran; the merge strategy's trace is the only proof that the
        # candidate arm executed what it was configured to execute.
        self._last_trace = merge_trace(result)
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
            raise RuntimeError(str(result.get("reason") or "web_search_unavailable"))

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
        return normalized

    def read(
        self, url: str, *, max_chars: int = 6000, timeout: float | None = None
    ) -> dict[str, Any]:
        return self.gateway.read(url, max_chars=max_chars, timeout=timeout)

    def warnings(self) -> list[dict[str, str]]:
        return list(self._warnings)

    def search_trace(self) -> dict[str, Any]:
        """How the last search was really executed, as far as it can be told.

        Empty for the default strategy and for direct GitHub URLs: nothing was
        merged, and a trace that always has fields would let Quality-0 report
        the candidate path for a run that never took it.
        """

        return dict(self._last_trace)
