from __future__ import annotations

from src.web.github_provider_pagination import (
    GitHubProviderRequestBudget,
    collect_rest_pages,
)


def test_rest_pagination_collects_multiple_pages_and_one_extra_item():
    calls: list[tuple[int, int]] = []

    def fetch(page: int, per_page: int):
        calls.append((page, per_page))
        pages = {
            1: [{"id": 1}, {"id": 2}],
            2: [{"id": 3}, {"id": 4}],
        }
        return pages.get(page, []), None

    result = collect_rest_pages(
        operation="reviews",
        limit=3,
        max_pages=5,
        page_size=2,
        fetch_page=fetch,
    )

    assert [item["id"] for item in result["items"]] == [1, 2, 3]
    assert calls == [(1, 2), (2, 2)]
    assert result["pages_fetched"] == 2
    assert result["truncated"] is True
    assert result["stop_reason"] == "item_budget_reached"


def test_rest_pagination_keeps_partial_items_after_later_provider_error():
    def fetch(page: int, _per_page: int):
        if page == 1:
            return [{"id": 1}, {"id": 2}], None
        return None, {"operation": "comments", "error": "github_http_502"}

    result = collect_rest_pages(
        operation="comments",
        limit=5,
        max_pages=5,
        page_size=2,
        fetch_page=fetch,
    )

    assert [item["id"] for item in result["items"]] == [1, 2]
    assert result["pages_fetched"] == 1
    assert result["truncated"] is True
    assert result["stop_reason"] == "provider_error"
    assert result["errors"][0]["error"] == "github_http_502"


def test_request_budget_records_exhausted_operation_without_overcalling():
    budget = GitHubProviderRequestBudget(max_requests=2, max_pages_per_collection=3)

    assert budget.claim("pull") is True
    assert budget.claim("files") is True
    assert budget.claim("reviews") is False
    assert budget.used_requests == 2
    assert budget.remaining_requests == 0
    assert budget.operations == {"pull": 1, "files": 1}
    assert budget.exhausted_operations == ["reviews"]
    assert budget.to_dict()["exhausted"] is True


def test_page_budget_exhaustion_is_not_reported_as_complete():
    result = collect_rest_pages(
        operation="jobs",
        limit=10,
        max_pages=1,
        page_size=2,
        fetch_page=lambda _page, _per_page: ([{"id": 1}, {"id": 2}], None),
    )

    assert result["items"] == [{"id": 1}, {"id": 2}]
    assert result["truncated"] is True
    assert result["stop_reason"] == "page_budget_exhausted"
