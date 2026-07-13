"""General-web adapter for durable research runs.

``WebLookupRun`` previously reused the news/RSS gateway, which made manual
research much narrower than the model-directed web tools. This adapter keeps the
existing service contract while delegating search and reading to the general
SearXNG/DuckDuckGo/GitHub-aware boundary.
"""

from __future__ import annotations

from typing import Any

from src.web.tool_gateway import GeneralWebGateway


class ResearchWebGateway:
    def __init__(self, gateway: GeneralWebGateway | None = None) -> None:
        self.gateway = gateway or GeneralWebGateway()
        self._warnings: list[dict[str, str]] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        result = self.gateway.search_exact(query, max_results=max_items)
        for error in result.get("provider_errors", []):
            warning = {
                "source": "general_web",
                "error_type": "provider_error",
                "message": str(error),
            }
            if warning["message"] and warning not in self._warnings:
                self._warnings.append(warning)
        status = str(result.get("status") or "")
        if status == "invalid_query":
            raise ValueError("Web lookup query is required")
        if status == "unavailable":
            raise RuntimeError(str(result.get("reason") or "web_search_unavailable"))
        return [
            dict(item)
            for item in result.get("results", [])
            if isinstance(item, dict)
        ]

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        return self.gateway.read(url, max_chars=max_chars)

    def warnings(self) -> list[dict[str, str]]:
        return list(self._warnings)
