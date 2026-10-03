import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.learning_review import (
    LearningReviewPage,
    ReviewPromptPreview,
    ReviewUnavailable,
)
from src.application.runtime_repository import get_learning_review_service


class FakeReviewService:
    def __init__(self):
        self.calls = []

    def build(self, thread_id, *, limit, offset, due_only):
        self.calls.append((thread_id, limit, offset, due_only))
        return LearningReviewPage(thread_id, "", (), 0, 0, limit, offset)

    def preview_prompt(self, thread_id, revision_id):
        self.calls.append((thread_id, revision_id))
        if revision_id == "missing":
            raise ReviewUnavailable("Review revision unavailable")
        if revision_id == "recent":
            raise ValueError("Review revision is no longer due")
        return ReviewPromptPreview(
            thread_id,
            "goal",
            revision_id,
            "2026-09-01T00:00:00Z",
            "Explain the concept",
        )


@pytest.fixture
def review_client():
    service = FakeReviewService()
    app.dependency_overrides[get_learning_review_service] = lambda: service
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.pop(get_learning_review_service, None)


def test_review_endpoint_pages_read_only_projection(
    runtime_test_context, review_client
):
    client, service = review_client
    session = runtime_test_context.session_service.create_session({})
    response = client.get(
        f"/sessions/{session.id}/reviews?limit=5&offset=2&due_only=true"
    )
    assert response.status_code == 200
    assert service.calls == [(session.id, 5, 2, True)]
    assert response.json()["source"] == "derived_read_only"
    assert response.json()["items"] == []


def test_missing_session_does_not_read_truth(review_client):
    client, service = review_client
    assert client.get("/sessions/missing/reviews").status_code == 404
    assert service.calls == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_review_endpoint_rejects_invalid_page(
    query, runtime_test_context, review_client
):
    client, service = review_client
    session = runtime_test_context.session_service.create_session({})
    assert client.get(f"/sessions/{session.id}/reviews?{query}").status_code == 422
    assert service.calls == []


def test_prompt_endpoint_exposes_preview_not_completed_review(
    runtime_test_context, review_client
):
    client, service = review_client
    session = runtime_test_context.session_service.create_session({})
    response = client.get(f"/sessions/{session.id}/reviews/revision/prompt")
    assert response.status_code == 200
    assert response.json()["status"] == "preview"
    assert response.json()["source"] == "derived_read_only"
    assert service.calls == [(session.id, "revision")]
    assert "user_response" not in response.text


@pytest.mark.parametrize("revision,status", [("missing", 404), ("recent", 409)])
def test_prompt_endpoint_maps_scope_and_due_errors(
    revision, status, runtime_test_context, review_client
):
    client, _service = review_client
    session = runtime_test_context.session_service.create_session({})
    assert (
        client.get(f"/sessions/{session.id}/reviews/{revision}/prompt").status_code
        == status
    )


def test_missing_session_cannot_prepare_prompt(review_client):
    client, service = review_client
    assert client.get("/sessions/missing/reviews/revision/prompt").status_code == 404
    assert service.calls == []
