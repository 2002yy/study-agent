from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.application.runtime_repository import get_session_attachment_service
from src.application.session_attachment_service import SessionAttachmentService
from src.domain.runtime_entities import SessionAttachment
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.rag import index as rag_index
from src.rag.schema import RagDocument, RagIndex
from src.repositories.session_attachment_repository import SessionAttachmentRepository


@pytest.fixture
def reading(tmp_path, monkeypatch):
    path = tmp_path / "long-term.json"
    monkeypatch.setattr(rag_index, "DEFAULT_RAG_INDEX_PATH", path)
    text = "# 第一节\n\n这是一整份正文，不是检索片段。\n" + "\n".join(
        f"第 {line} 行" for line in range(4, 221)
    )
    document = RagDocument(
        source_path=str(tmp_path / "deleted-original.md"), title="读书笔记",
        text=text, content_hash=sha256(text.encode()).hexdigest(),
        file_type="md", document_id="doc-reader", revision_id="revision-1",
        evidence_status="excluded",
    )
    rag_index.save_rag_index(RagIndex(1, (document,), ()), path)
    service = SessionAttachmentService(
        SessionAttachmentRepository(RuntimeDatabase(tmp_path / "runtime.db")),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp.json",
    )
    app.dependency_overrides[get_session_attachment_service] = lambda: service
    try:
        yield TestClient(app), path, document, service
    finally:
        app.dependency_overrides.pop(get_session_attachment_service, None)


def test_full_parsed_text_is_read_without_original_file_chunks_or_writes(reading):
    http, path, document, _ = reading
    before = path.read_bytes()
    response = http.get("/knowledge-base/documents/doc-reader/reading")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_version"] == "document-reading-v1"
    assert body["representation"] == "indexed_text"
    assert body["text"] == "\n".join(document.text.splitlines()[:100])
    assert (body["start_line"], body["end_line"], body["total_lines"]) == (1, 100, 220)
    assert body["evidence_status"] == "excluded"
    assert path.read_bytes() == before
    page = http.get("/knowledge-base/documents/doc-reader/reading", params={
        "start_line": 201, "expected_revision": body["revision_id"],
    }).json()
    assert page["text"] == "\n".join(document.text.splitlines()[200:])
    assert (page["start_line"], page["end_line"]) == (201, 220)


def test_stale_revision_and_deleted_document_fail_closed(reading):
    http, path, document, _ = reading
    rag_index.save_rag_index(RagIndex(2, (replace(document, revision_id="revision-2"),), ()), path)
    assert http.get("/knowledge-base/documents/doc-reader/reading", params={
        "expected_revision": "revision-1",
    }).status_code == 409
    rag_index.save_rag_index(RagIndex(3, (), ()), path)
    assert http.get("/knowledge-base/documents/doc-reader/reading").status_code == 404


@pytest.mark.parametrize("params", [
    {"start_line": 0}, {"start_line": 221}, {"limit": 0}, {"limit": 201},
])
def test_invalid_range_is_rejected(reading, params):
    http, _, _, _ = reading
    assert http.get("/knowledge-base/documents/doc-reader/reading", params=params).status_code == 422


def test_caller_cannot_select_a_different_index_or_source_path(reading, tmp_path):
    http, _, document, _ = reading
    other = tmp_path / "private-index.json"
    rag_index.save_rag_index(RagIndex(1, (replace(document, document_id="private-doc"),), ()), other)
    assert http.get("/knowledge-base/documents/private-doc/reading", params={
        "index_path": str(other), "source_path": document.source_path,
    }).status_code == 404


def test_utf8_window_limit_has_no_silent_truncation(reading):
    http, path, document, _ = reading
    rag_index.save_rag_index(RagIndex(1, (replace(document, text="读" * 22000),), ()), path)
    assert http.get("/knowledge-base/documents/doc-reader/reading").status_code == 413


@pytest.mark.parametrize("file_type", ["pdf", "docx"])
def test_binary_document_is_explicitly_indexed_text_not_original_pixels(reading, file_type):
    http, path, document, _ = reading
    rag_index.save_rag_index(RagIndex(1, (replace(document, file_type=file_type),), ()), path)
    body = http.get("/knowledge-base/documents/doc-reader/reading").json()
    assert body["file_type"] == file_type
    assert body["representation"] == "indexed_text"
    assert "page" not in body and "region" not in body


def test_legacy_document_uses_existing_identity_fallback(reading):
    http, path, document, _ = reading
    legacy = replace(document, document_id="", revision_id="")
    rag_index.save_rag_index(RagIndex(1, (legacy,), ()), path)
    body = http.get(f"/knowledge-base/documents/{legacy.content_hash}/reading").json()
    assert body["document_id"] == body["revision_id"] == legacy.content_hash


def test_attachment_double_owner_binding_and_lifecycle(reading):
    http, _, document, service = reading
    attachment = service.repository.create(SessionAttachment(
        thread_id="thread-a", filename="notes.md", status="ready",
    ))
    indexed = replace(document, metadata={"thread_id":"thread-a", "attachment_id":attachment.id})
    rag_index.save_rag_index(RagIndex(1, (indexed,), ()), service.temp_index_path)
    path = f"/sessions/thread-a/attachments/{attachment.id}/reading"
    before = service.repository.get(attachment.id)
    assert http.get(path).json()["scope"] == "session"
    assert service.repository.get(attachment.id) == before
    assert http.get(path.replace("thread-a", "thread-b")).status_code == 404
    rag_index.save_rag_index(RagIndex(1, (replace(indexed, metadata={
        "thread_id":"thread-b", "attachment_id":attachment.id,
    }),), ()), service.temp_index_path)
    assert http.get(path).status_code == 404
    pending = service.repository.create(SessionAttachment(thread_id="thread-a",filename="pending.md",status="parsing"))
    assert http.get(f"/sessions/thread-a/attachments/{pending.id}/reading").status_code == 409
    service.repository.delete(attachment.id)
    assert http.get(path).status_code == 404


def test_image_description_is_not_document_original(reading):
    http, path, document, _ = reading
    rag_index.save_rag_index(RagIndex(1, (replace(document, file_type="png"),), ()), path)
    assert http.get("/knowledge-base/documents/doc-reader/reading").status_code == 409
