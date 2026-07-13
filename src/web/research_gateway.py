"""General-web search adapter for durable research runs.

``WebLookupRun`` previously reused the news/RSS gateway, which made manual
research much narrower than the model-directed web tools. This adapter keeps the
existing service contract while delegating to the general SearXNG/DuckDuckGo
search boundary.
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
        return [dict(item) for item in result.get("results", []) if isinstance(item, dict)]

    def warnings(self) -> list[dict[str, str]]:
        return list(self._warnings)
