from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from src.api.app import app
from src.application.runtime_repository import (
    get_session_attachment_service,
    get_web_lookup_service,
)
from src.application.session_attachment_service import SessionAttachmentService
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.rag import index as rag_index
from src.rag.loader import load_document
from src.rag.schema import RagIndex
from src.repositories.session_attachment_repository import SessionAttachmentRepository
from src.repositories.web_lookup_repository import WebLookupRepository


def sample_pdf(text="Original page", pages=2):
    writer = PdfWriter()
    for number in range(1, pages + 1):
        page = writer.add_blank_page(width=420, height=594)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            f"BT /F1 22 Tf 40 530 Td ({text} {number}) Tj ET\n0.2 0.36 0.5 rg 40 430 280 50 re f".encode()
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def original(tmp_path, monkeypatch):
    path = tmp_path / "index.json"
    monkeypatch.setattr(rag_index, "DEFAULT_RAG_INDEX_PATH", path)
    file = tmp_path / "source.pdf"
    file.write_bytes(sample_pdf())
    document = load_document(file)
    rag_index.save_rag_index(RagIndex(1, (document,), ()), path)
    database = RuntimeDatabase(tmp_path / "runtime.db")
    attachments = SessionAttachmentService(
        SessionAttachmentRepository(database),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp.json",
    )
    web = WebLookupRepository(database)
    app.dependency_overrides[get_session_attachment_service] = lambda: attachments
    app.dependency_overrides[get_web_lookup_service] = lambda: SimpleNamespace(
        get=web.get
    )
    try:
        yield TestClient(app), file, document, path, attachments, web
    finally:
        app.dependency_overrides.pop(get_session_attachment_service, None)
        app.dependency_overrides.pop(get_web_lookup_service, None)


def test_original_pdf_bytes_page_mapping_and_no_writes(original):
    http, file, document, path, _, _ = original
    before = path.read_bytes()
    endpoint = f"/knowledge-base/documents/{document.document_id}"
    response = http.get(
        endpoint + "/original", params={"expected_revision": document.revision_id}
    )
    assert response.status_code == 200
    assert response.content == file.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    reading = http.get(endpoint + "/reading").json()
    assert reading["pdf_pages"] == 2
    assert reading["pdf_page_map"] == [{"page": 1, "line": 1}, {"page": 2, "line": 4}]
    assert path.read_bytes() == before


def test_pdf_stale_replaced_missing_and_arbitrary_path_fail_closed(original):
    http, file, document, _, _, _ = original
    endpoint = f"/knowledge-base/documents/{document.document_id}/original"
    assert http.get(endpoint).status_code == 409
    assert http.get(endpoint, params={"expected_revision": "old"}).status_code == 409
    assert (
        http.get(
            "/knowledge-base/documents/unknown/original",
            params={
                "source_path": str(file),
                "expected_revision": document.revision_id,
            },
        ).status_code
        == 404
    )
    file.write_bytes(sample_pdf("Replaced source"))
    assert (
        http.get(
            endpoint, params={"expected_revision": document.revision_id}
        ).status_code
        == 409
    )
    file.unlink()
    assert (
        http.get(
            endpoint, params={"expected_revision": document.revision_id}
        ).status_code
        == 404
    )


def test_legacy_pdf_requires_matching_parsed_content(original):
    http, file, document, path, _, _ = original
    legacy = replace(document, metadata={"pdf_pages": 2})
    rag_index.save_rag_index(RagIndex(1, (legacy,), ()), path)
    endpoint = f"/knowledge-base/documents/{document.document_id}/original"
    assert (
        http.get(
            endpoint, params={"expected_revision": document.revision_id}
        ).status_code
        == 200
    )
    file.write_bytes(sample_pdf("Wrong legacy text"))
    assert (
        http.get(
            endpoint, params={"expected_revision": document.revision_id}
        ).status_code
        == 409
    )


def test_pdf_page_labels_in_text_do_not_authorize_a_page_jump(original):
    http, _, document, path, _, _ = original
    legacy = replace(
        document,
        text="[Page 1]\nLiteral example\n[Page 2]\nStill page one",
        metadata={"pdf_pages": 2},
    )
    rag_index.save_rag_index(RagIndex(1, (legacy,), ()), path)
    assert (
        http.get(f"/knowledge-base/documents/{document.document_id}/reading").json()[
            "pdf_page_map"
        ]
        == []
    )


def test_session_pdf_owner_hash_and_existing_auth(original, monkeypatch):
    http, file, _, _, service, _ = original
    attachment = service.upload(
        "thread-a", "lecture.pdf", file.read_bytes(), content_type="application/pdf"
    )
    parsed = rag_index.load_rag_index(service.temp_index_path).documents[0]
    endpoint = f"/sessions/thread-a/attachments/{attachment.id}/original"
    params = {"expected_revision": parsed.revision_id}
    assert http.get(endpoint, params=params).status_code == 200
    assert (
        http.get(endpoint.replace("thread-a", "thread-b"), params=params).status_code
        == 404
    )
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", "reading-token")
    assert http.get(endpoint, params=params).status_code == 401
    assert (
        http.get(
            endpoint, params=params, headers={"X-Study-Agent-Token": "reading-token"}
        ).status_code
        == 200
    )
    monkeypatch.delenv("STUDY_AGENT_API_TOKEN")
    Path(attachment.storage_path).write_bytes(sample_pdf("Changed attachment"))
    assert http.get(endpoint, params=params).status_code == 409


def web_run(repository, *, selected=False, truncated=False):
    url = "https://example.org/retained"
    read = {
        "ok": True,
        "url": url,
        "content": "# Saved source\nFull retained line\nThird line",
        "content_truncated": truncated,
    }
    return repository.create(
        WebLookupRun(
            owner_thread_id="thread-a",
            status="completed",
            selected_sources=[
                {
                    "item": {"url": url, "title": "Saved source"},
                    "assessment": {},
                    "read": read,
                }
            ]
            if selected
            else [],
            research_context={}
            if selected
            else {
                "tool_trace": {
                    "evidence_calls": [
                        {"name": "web_read", "arguments": {"url": url}, "result": read}
                    ]
                }
            },
        )
    ), url


@pytest.mark.parametrize("selected", [False, True])
def test_saved_web_reads_are_owner_bound_windowed_and_never_refetched(
    original, selected
):
    http, _, _, _, _, repository = original
    run, url = web_run(repository, selected=selected, truncated=True)
    before = repository.get(run.id)
    endpoint = f"/sessions/thread-a/research-runs/{run.id}/sources/reading"
    response = http.get(endpoint, params={"url": url, "limit": 2})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["representation"] == "saved_web_text" and body["content_truncated"] is True
    )
    assert body["text"] == "# Saved source\nFull retained line"
    assert (
        body["content_hash"]
        == sha256("# Saved source\nFull retained line\nThird line".encode()).hexdigest()
    )
    assert (
        http.get(
            endpoint,
            params={
                "url": url,
                "start_line": 3,
                "expected_revision": body["revision_id"],
            },
        ).json()["text"]
        == "Third line"
    )
    assert (
        http.get(endpoint, params={"url": url, "expected_revision": "old"}).status_code
        == 409
    )
    assert (
        http.get(
            endpoint.replace("thread-a", "thread-b"), params={"url": url}
        ).status_code
        == 404
    )
    assert (
        http.get(endpoint, params={"url": "http://127.0.0.1/private"}).status_code
        == 409
    )
    assert repository.get(run.id) == before


def test_search_candidates_failed_and_ambiguous_reads_are_not_reading_authority(
    original,
):
    http, _, _, _, _, repository = original
    run = repository.create(
        WebLookupRun(
            owner_thread_id="thread-a",
            items=[{"url": "https://example.org"}],
            research_context={
                "tool_trace": {
                    "calls": [
                        {
                            "name": "web_read",
                            "arguments": {"url": "https://example.org"},
                            "result": {"ok": False, "content": "Failed"},
                        }
                    ]
                }
            },
        )
    )
    assert (
        http.get(
            f"/sessions/thread-a/research-runs/{run.id}/sources/reading",
            params={"url": "https://example.org"},
        ).status_code
        == 409
    )
    ambiguous = repository.create(
        WebLookupRun(
            owner_thread_id="thread-a",
            selected_sources=[
                {
                    "item": {"url": "https://example.org"},
                    "assessment": {},
                    "read": {"ok": True, "content": text},
                }
                for text in ("first", "different")
            ],
        )
    )
    assert (
        http.get(
            f"/sessions/thread-a/research-runs/{ambiguous.id}/sources/reading",
            params={"url": "https://example.org"},
        ).status_code
        == 409
    )
