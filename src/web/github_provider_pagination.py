"""Shared request budgets and deterministic REST pagination for GitHub providers.

The work-item layer composes several REST and GraphQL collections in one user
request. Item limits alone do not bound provider traffic, so this module tracks a
single request budget across all sub-operations and gives every collection a page
budget. Partial pages remain usable and stop reasons are explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Callable


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


@dataclass
class GitHubProviderRequestBudget:
    """Mutable request counter shared by one composed GitHub operation."""

    max_requests: int = 24
    max_pages_per_collection: int = 10
    used_requests: int = 0
    operations: dict[str, int] = field(default_factory=dict)
    exhausted_operations: list[str] = field(default_factory=list)

    @classmethod
    def from_env(
        cls,
        *,
        max_requests: int | None = None,
        max_pages_per_collection: int | None = None,
    ) -> "GitHubProviderRequestBudget":
        request_limit = (
            max_requests
            if max_requests is not None
            else _env_int(
                "GITHUB_PROVIDER_MAX_REQUESTS",
                24,
                minimum=1,
                maximum=128,
            )
        )
        page_limit = (
            max_pages_per_collection
            if max_pages_per_collection is not None
            else _env_int(
                "GITHUB_PROVIDER_MAX_PAGES_PER_COLLECTION",
                10,
                minimum=1,
                maximum=50,
            )
        )
        return cls(
            max_requests=max(1, min(int(request_limit), 128)),
            max_pages_per_collection=max(1, min(int(page_limit), 50)),
        )

    @property
    def remaining_requests(self) -> int:
        return max(0, self.max_requests - self.used_requests)

    @property
    def exhausted(self) -> bool:
        return self.remaining_requests <= 0

    def claim(self, operation: str) -> bool:
        name = str(operation or "github_provider")
        if self.exhausted:
            if name not in self.exhausted_operations:
                self.exhausted_operations.append(name)
            return False
        self.used_requests += 1
        self.operations[name] = self.operations.get(name, 0) + 1
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_requests": self.max_requests,
            "used_requests": self.used_requests,
            "remaining_requests": self.remaining_requests,
            "max_pages_per_collection": self.max_pages_per_collection,
            "operations": dict(sorted(self.operations.items())),
            "exhausted": self.exhausted,
            "exhausted_operations": list(self.exhausted_operations),
        }


def _items(payload: Any, *, key: str = "") -> list[dict[str, Any]]:
    value = payload.get(key) if key and isinstance(payload, dict) else payload
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def collect_rest_pages(
    *,
    operation: str,
    limit: int,
    max_pages: int,
    fetch_page: Callable[[int, int], tuple[Any | None, dict[str, str] | None]],
    key: str = "",
    page_size: int | None = None,
) -> dict[str, Any]:
    """Collect a REST list with deterministic page and item bounds.

    ``fetch_page`` receives ``(page, per_page)`` and is responsible for consuming
    the shared request budget. One extra item is collected when possible so a
    result exactly at the requested limit can still report truncation.
    """

    item_limit = max(1, int(limit))
    page_limit = max(1, int(max_pages))
    configured_page_size = page_size or _env_int(
        "GITHUB_PROVIDER_PAGE_SIZE",
        100,
        minimum=1,
        maximum=100,
    )
    per_page = max(1, min(int(configured_page_size), 100, item_limit + 1))
    target_count = item_limit + 1
    collected: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    provider_count = 0
    pages_fetched = 0
    stop_reason = "provider_exhausted"
    provider_has_more = False

    for page in range(1, page_limit + 1):
        payload, error = fetch_page(page, per_page)
        if error is not None:
            errors.append(error)
            stop_reason = (
                "request_budget_exhausted"
                if error.get("error") == "provider_request_budget_exhausted"
                else "provider_error"
            )
            break
        pages_fetched += 1
        page_items = _items(payload, key=key)
        if isinstance(payload, dict):
            provider_count = max(
                provider_count,
                int(payload.get("total_count") or payload.get("totalCount") or 0),
            )
        collected.extend(page_items)
        if len(collected) >= target_count:
            stop_reason = "item_budget_reached"
            provider_has_more = True
            break
        if len(page_items) < per_page:
            stop_reason = "provider_exhausted"
            provider_has_more = False
            break
        provider_has_more = True
    else:
        stop_reason = "page_budget_exhausted"

    visible = collected[:item_limit]
    provider_count = max(provider_count, len(collected))
    incomplete_stop = stop_reason in {
        "page_budget_exhausted",
        "request_budget_exhausted",
        "provider_error",
    }
    truncated = (
        len(collected) > item_limit
        or provider_count > len(visible)
        or stop_reason == "item_budget_reached"
        or incomplete_stop
        or provider_has_more and len(visible) >= item_limit
    )
    return {
        "items": visible,
        "provider_count": provider_count,
        "pages_fetched": pages_fetched,
        "truncated": bool(truncated),
        "stop_reason": stop_reason,
        "errors": errors,
        "per_page": per_page,
        "max_pages": page_limit,
    }
