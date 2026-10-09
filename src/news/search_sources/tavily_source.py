"""Optional Tavily search provider (B-Search-2B9-D).

Opt-in and OFF by default. The API key is read only from ``TAVILY_API_KEY`` (never
committed). Basic web search only — no answer synthesis, no raw content — so the
existing Reader still fetches bodies. Calls and errors are explicitly countable; a
missing key or exhausted quota fails diagnosably without touching Agent budgets.
"""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

_LAST_ERROR = ""
_CALLS = 0
_ENDPOINT = "https://api.tavily.com/search"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def tavily_api_key() -> str:
    return (os.getenv("TAVILY_API_KEY") or "").strip()


def tavily_enabled() -> bool:
    return _env_flag("WEB_ENABLE_TAVILY", default=False) and bool(tavily_api_key())


def get_last_tavily_error() -> str:
    return _LAST_ERROR


def get_tavily_call_count() -> int:
    return _CALLS


def search_tavily(query: str, *, max_results: int = 5, timeout: float = 8.0,
                  endpoint: str = _ENDPOINT) -> list[dict[str, str]]:
    """Return ``[{title,url,snippet,source}]`` or ``[]`` (with a diagnosable error)."""
    global _LAST_ERROR, _CALLS
    _LAST_ERROR = ""
    key = tavily_api_key()
    if not key:
        _LAST_ERROR = "missing_api_key"
        return []
    payload = {
        "api_key": key,
        "query": str(query or ""),
        "search_depth": "basic",
        "max_results": max(1, min(int(max_results), 20)),
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        _CALLS += 1
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 (endpoint is fixed)
            data = json.loads(response.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        _LAST_ERROR = f"{type(exc).__name__}: {exc}"
        return []
    out: list[dict[str, str]] = []
    for item in (data.get("results") or [])[:max_results]:
        url = str(item.get("url") or "")
        title = str(item.get("title") or "")
        if url and title:
            out.append({"title": title, "url": url,
                        "snippet": str(item.get("content") or ""), "source": "Tavily"})
    return out
