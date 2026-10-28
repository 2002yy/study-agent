"""G14 API adapter tests for temporary session attachments."""

from __future__ import annotations

import pytest


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.session_attachment_repository import (
        SessionAttachmentRepository,
    )
    from src.application.runtime_repository import (
        get_session_attachment_service,
    )
    from src.application.session_attachment_service import (
        SessionAttachmentService,
    )
    from src.api.app import app as fastapi_app

    service = SessionAttachmentService(
        SessionAttachmentRepository(RuntimeDatabase(tmp_path / "runtime.db")),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term.json",
    )
    fastapi_app.dependency_overrides[get_session_attachment_service] = (
        lambda: service
    )
    try:
        yield TestClient(fastapi_app), service
    finally:
        fastapi_app.dependency_overrides.pop(
            get_session_attachment_service, None
        )


def test_upload_list_delete_roundtrip(client):
    http, _ = client

    uploaded = http.post(
        "/sessions/thread_api/attachments",
        files={
            "file": (
                "notes.md",
                "# API 笔记\n\n检索过滤按 thread 硬隔离。".encode("utf-8"),
                "text/markdown",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["status"] == "ready"
    assert [entry["stage"] for entry in body["stage_history"]][-1] == "indexing"

    listed = http.get("/sessions/thread_api/attachments").json()
    assert listed["max_files_per_thread"] == 10
    assert len(listed["attachments"]) == 1
    assert listed["attachments"][0]["id"] == body["id"]

    deleted = http.delete(f"/attachments/{body['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert http.get("/sessions/thread_api/attachments").json()["attachments"] == []


def test_unsupported_type_maps_to_400(client):
    http, _ = client
    response = http.post(
        "/sessions/thread_api/attachments",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_csv_upload_is_accepted_and_indexed(client):
    http, _ = client

    uploaded = http.post(
        "/sessions/thread_csv/attachments",
        files={
            "file": (
                "counts.csv",
                "category,value\ngamma,900\n".encode("utf-8"),
                "text/csv",
            )
        },
    )

    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["status"] == "ready"
    assert body["filename"] == "counts.csv"
    assert body["mime_type"] == "text/csv"
    assert [entry["stage"] for entry in body["stage_history"]][-1] == "indexing"


def test_retry_unknown_id_maps_to_404_and_promote_409(client):
    http, service = client

    missing = http.post("/attachments/att_missing/retry")
    assert missing.status_code == 404

    attachment = service.upload(
        "thread_z", "broken.pdf", b"%PDF-1.4 corrupt"
    )
    promote_failed = http.post(f"/attachments/{attachment.id}/promote")
    assert promote_failed.status_code == 409
