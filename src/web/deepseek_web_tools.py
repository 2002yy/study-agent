"""Opt-in DeepSeek Search/Fetch transports (no model requests).

The two independent tool APIs are billable. Both the feature flag and a
positive per-process request cap must be set before any request can leave the
process. The cap is a local safety guard, *not* a durable multi-worker ledger.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request, urlopen

from src.news.url_normalizer import is_public_http_url

_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
_FETCH_URL = "https://api.deepseek.com/v1/tools/fetch"
_MAX_RESPONSE_BYTES = 1_500_000
_SECRET_QUERY_PARAMS = frozenset({
    "access_token", "api_key", "auth", "authorization", "key", "jwt",
    "sig", "signature", "token", "x-amz-signature", "x-goog-signature",
})
_used_requests = {"search": 0, "fetch": 0}
_request_lock = threading.Lock()


def _enabled(kind: str) -> bool:
    return os.getenv(f"WEB_DEEPSEEK_{kind.upper()}_ENABLED", "false").lower() in {
        "1", "true", "yes", "on",
    }


def _reserve_request(kind: str) -> str:
    """Return an opaque reason when a paid call is not permitted."""

    if not _enabled(kind):
        return "disabled"
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key or key == "your_api_key_here":
        return "missing_api_key"
    try:
        cap = int(os.getenv(f"WEB_DEEPSEEK_{kind.upper()}_MAX_REQUESTS", "0"))
    except ValueError:
        return "invalid_request_cap"
    if cap <= 0:
        return "request_cap_disabled"
    with _request_lock:
        if _used_requests[kind] >= cap:
            return "request_cap_exhausted"
        _used_requests[kind] += 1
    return ""


def _request_json(
    kind: str, payload: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], str]:
    refusal = _reserve_request(kind)
    if refusal:
        return {}, refusal
    request = Request(
        _SEARCH_URL if kind == "search" else _FETCH_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY'].strip()}",
            "Content-Type": "application/json",
            "User-Agent": "StudyAgent/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(0.25, timeout)) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # Never emit exception strings, response bodies or the credential.
        return {}, f"http_status:{exc.code}"
    except (URLError, TimeoutError, OSError):
        return {}, "transport_failed"
    if len(raw) > _MAX_RESPONSE_BYTES:
        return {}, "response_too_large"
    try:
        decoded = json.loads(raw)
    except (UnicodeError, ValueError):
        return {}, "invalid_json"
    if not isinstance(decoded, dict):
        return {}, "invalid_response_shape"
    if "error" in decoded:
        return {}, "provider_error"
    return decoded, ""


def search_deepseek(
    query: str, limit: int, timeout: float, *, original_question: str = ""
) -> tuple[list[dict[str, str]], str]:
    """Return candidates only; an ordinary web_read is still required."""

    focused = " ".join(query.split())
    if not focused or len(focused) > 128:
        return [], "deepseek_search:invalid_query"
    payload: dict[str, Any] = {
        "query": focused,
        "count": max(1, min(int(limit), 50)),
        "need_content": False,
    }
    if original_question and len(original_question) <= 128:
        payload["ori_question"] = original_question
    data, error = _request_json("search", payload, timeout)
    if error:
        return [], f"deepseek_search:{error}"
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        return [], "deepseek_search:invalid_response_shape"
    results: list[dict[str, str]] = []
    for item in raw_results[: payload["count"]]:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or len(url) > 8192 or not is_public_http_url(url):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        snippet = item.get("summary") or item.get("snippet") or ""
        results.append({
            "title": title.strip()[:350],
            "url": url,
            "snippet": str(snippet)[:2000],
            "source": "DeepSeek Search",
            "published_at": str(item.get("date") or "")[:50],
        })
    return (
        results,
        "" if results or not raw_results else "deepseek_search:no_usable_results",
    )


def fetch_deepseek(
    url: str, *, max_chars: int, timeout: float
) -> tuple[dict[str, str] | None, str]:
    """Fetch a public page as Markdown, preserving the requested source URL."""

    if (
        not is_public_http_url(url)
        or len(url) > 8192
        or any(
            name.lower() in _SECRET_QUERY_PARAMS
            for name, _value in parse_qsl(urlparse(url).query)
        )
    ):
        return None, "deepseek_fetch:unsafe_url"
    data, error = _request_json("fetch", {"url": url}, timeout)
    if error:
        return None, f"deepseek_fetch:{error}"
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "deepseek_fetch:empty_content"
    return {
        "title": str(data.get("title") or "")[:350],
        "content": content[:max(1, min(int(max_chars), 20_000))],
    }, ""
