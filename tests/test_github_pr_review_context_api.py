from __future__ import annotations

from fastapi.testclient import TestClient

from src.api import app
from src.api.routes import github_review_routes
from src.api.routes.github_routes import (
    get_github_history_service,
    get_github_work_item_service,
)
from src.application.runtime_repository import get_github_snapshot_service


class _FakeDependency:
    pass


class _FakeReviewContextService:
    def __init__(self, work_item_service, change_impact_service) -> None:
        assert isinstance(work_item_service, _FakeDependency)
        assert change_impact_service is not None

    def build(self, repo_url: str, number: int, **kwargs) -> dict:
        return {
            "ok": True,
            "status": "resolved",
            "kind": "github_pr_review_context",
            "repository": repo_url,
            "number": number,
            "budget": kwargs,
            "verdict": {
                "status": "not_generated",
                "reason": "review_context_is_evidence_not_a_correctness_verdict",
            },
        }


def test_pr_review_context_endpoint_forwards_bounded_request(monkeypatch):
    dependency = _FakeDependency()
    app.dependency_overrides[get_github_snapshot_service] = lambda: dependency
    app.dependency_overrides[get_github_history_service] = lambda: dependency
    app.dependency_overrides[get_github_work_item_service] = lambda: dependency
    monkeypatch.setattr(
        github_review_routes,
        "GitHubPRReviewContextService",
        _FakeReviewContextService,
    )
    client = TestClient(app)

    try:
        response = client.post(
            "/github-pr-review-context",
            json={
                "repo_url": "https://github.com/openai/example",
                "number": 7,
                "max_files": 10,
                "max_symbols": 20,
                "max_comments": 30,
                "max_reviews": 40,
                "depth": 3,
                "max_impact_files": 50,
                "max_edges": 200,
                "max_provider_requests": 18,
                "max_pages_per_collection": 4,
            },
        )
    finally:
        app.dependency_overrides.pop(get_github_snapshot_service, None)
        app.dependency_overrides.pop(get_github_history_service, None)
        app.dependency_overrides.pop(get_github_work_item_service, None)

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["kind"] == "github_pr_review_context"
    assert result["number"] == 7
    assert result["budget"] == {
        "max_files": 10,
        "max_symbols": 20,
        "max_comments": 30,
        "max_reviews": 40,
        "depth": 3,
        "max_impact_files": 50,
        "max_edges": 200,
        "max_provider_requests": 18,
        "max_pages_per_collection": 4,
    }
    assert result["verdict"]["status"] == "not_generated"


def test_pr_review_context_endpoint_rejects_out_of_range_budget():
    client = TestClient(app)

    response = client.post(
        "/github-pr-review-context",
        json={
            "repo_url": "https://github.com/openai/example",
            "number": 7,
            "max_provider_requests": 129,
        },
    )

    assert response.status_code == 422
