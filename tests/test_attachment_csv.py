"""CSV session attachments: real upload, parse, index and per-thread retrieval.

FILE-02 in the Quality-0 task set attaches a CSV, so the product path has to
accept it. The contract is deliberately narrow: one UTF-8 CSV, indexed as text
so every header and data row stays citable. No spreadsheet semantics, no Excel.
"""

from __future__ import annotations

import pytest

from src.application.session_attachment_service import SessionAttachmentService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.rag.loader import load_document
from src.repositories.session_attachment_repository import (
    SessionAttachmentRepository,
)

CSV_TEXT = (
    "category,value\n"
    "alpha,10\n"
    "alpha,12\n"
    "beta,9\n"
    "beta,\n"
    "gamma,11\n"
    "gamma,900\n"
    "delta,8\n"
)


def _service(tmp_path) -> SessionAttachmentService:
    return SessionAttachmentService(
        SessionAttachmentRepository(RuntimeDatabase(tmp_path / "runtime.db")),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term_index.json",
    )


def _upload(service: SessionAttachmentService, data: bytes, *, name="counts.csv"):
    return service.upload(
        "thread_csv", name, data, content_type="text/csv"
    )


def test_csv_upload_reaches_ready_with_every_row_indexed(tmp_path):
    service = _service(tmp_path)

    attachment = _upload(service, CSV_TEXT.encode("utf-8"))

    assert attachment.status == "ready"
    stages = [entry["stage"] for entry in attachment.stage_history]
    assert stages == ["upload", "parsing", "chunking", "indexing"]

    snapshot = service.temp_index_snapshot()
    assert snapshot is not None
    document = next(iter(snapshot.documents))
    assert document.file_type == "csv"
    assert document.title == "counts.csv"
    # Header and the anomaly row both survive into the indexed text.
    assert "category,value" in document.text
    assert "gamma,900" in document.text
    assert document.metadata["csv_rows"] == 8
    assert document.metadata["csv_columns"] == 2
    assert document.metadata["csv_has_header"] is True
    # The exact uploaded bytes are recorded, so two arms can be compared.
    assert document.metadata["source_sha256"] == (
        __import__("hashlib").sha256(CSV_TEXT.encode("utf-8")).hexdigest()
    )


def test_csv_retrieval_is_scoped_to_its_thread(tmp_path):
    service = _service(tmp_path)
    _upload(service, CSV_TEXT.encode("utf-8"))

    own = service.retrieve_for_thread("gamma 900", "thread_csv")
    other = service.retrieve_for_thread("gamma 900", "thread_other")

    assert own, "the uploaded CSV must be retrievable inside its thread"
    assert any("900" in hit.chunk.text for hit in own)
    assert other == [], "another thread must never see the CSV"


def test_csv_with_utf8_bom_keeps_a_clean_header(tmp_path):
    service = _service(tmp_path)

    attachment = _upload(
        service, b"\xef\xbb\xbf" + CSV_TEXT.encode("utf-8")
    )

    assert attachment.status == "ready"
    snapshot = service.temp_index_snapshot()
    document = next(iter(snapshot.documents))
    assert not document.text.startswith("\ufeff")
    assert document.text.startswith("category,value")


def test_csv_with_trailing_crlf_is_normalised(tmp_path):
    service = _service(tmp_path)

    attachment = _upload(
        service, CSV_TEXT.replace("\n", "\r\n").encode("utf-8")
    )

    assert attachment.status == "ready"
    snapshot = service.temp_index_snapshot()
    document = next(iter(snapshot.documents))
    assert "\r" not in document.text
    assert "gamma,900" in document.text


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"a,b\n\xff\xfe\n", "UTF-8"),
        (b"a,b\n1,\x00\n", "NUL"),
    ],
)
def test_unreadable_csv_fails_with_a_reason_instead_of_mojibake(
    tmp_path, data, expected
):
    service = _service(tmp_path)

    attachment = _upload(service, data)

    assert attachment.status == "failed"
    assert expected in attachment.stage_error
    # A failed attachment contributes nothing to retrieval.
    assert service.retrieve_for_thread("a b", "thread_csv") == []


def test_empty_csv_is_rejected_before_storage(tmp_path):
    service = _service(tmp_path)

    with pytest.raises(ValueError, match="empty"):
        _upload(service, b"")


def test_loader_reports_shape_without_a_spreadsheet_parser(tmp_path):
    path = tmp_path / "counts.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")

    document = load_document(path)

    assert document.file_type == "csv"
    assert document.metadata["csv_rows"] == 8
    assert document.metadata["csv_columns"] == 2
    assert "beta," in document.text
