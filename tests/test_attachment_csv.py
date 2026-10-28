"""CSV session attachments: real upload, parse, index and per-thread retrieval.

FILE-02 in the Quality-0 task set attaches a CSV, so the product path has to
accept it. The contract is deliberately narrow: one UTF-8 CSV, indexed as text
so every header and data row stays citable. No spreadsheet semantics, no Excel.

The hard part is not the extension: CSV whitespace and empty lines are *data*.
Nothing on the way to the index may strip a line, collapse a blank line or
reflow a cell, and optional metadata must never fail an otherwise valid file.
"""

from __future__ import annotations

import hashlib

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

# A cell that is only spaces, and a cell containing a blank line, are both legal
# CSV and both would be damaged by prose normalization.
LAYOUT_CSV = (
    'category,value\n'
    'A,"   "\n'
    'B,"第一行\n'
    '\n'
    '第三行"\n'
)


def _service(tmp_path) -> SessionAttachmentService:
    return SessionAttachmentService(
        SessionAttachmentRepository(RuntimeDatabase(tmp_path / "runtime.db")),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term_index.json",
    )


def _upload(service: SessionAttachmentService, data: bytes, *, name="counts.csv"):
    return service.upload("thread_csv", name, data, content_type="text/csv")


def _indexed_documents(service: SessionAttachmentService):
    snapshot = service.temp_index_snapshot()
    assert snapshot is not None
    return {doc.title: doc for doc in snapshot.documents}


def test_csv_upload_reaches_ready_with_every_row_indexed(tmp_path):
    service = _service(tmp_path)

    attachment = _upload(service, CSV_TEXT.encode("utf-8"))

    assert attachment.status == "ready"
    stages = [entry["stage"] for entry in attachment.stage_history]
    assert stages == ["upload", "parsing", "chunking", "indexing"]

    document = _indexed_documents(service)["counts.csv"]
    assert document.file_type == "csv"
    # The indexed text is the file, not a reflowed copy of it.
    assert document.text == CSV_TEXT
    assert document.metadata["csv_rows"] == 8  # records, header included
    assert document.metadata["csv_columns"] == 2
    # Nothing in a CSV proves the first row is a header.
    assert document.metadata["csv_has_header"] is None
    assert document.metadata["source_sha256"] == (
        hashlib.sha256(CSV_TEXT.encode("utf-8")).hexdigest()
    )


def test_csv_cells_survive_into_the_index_unchanged(tmp_path):
    service = _service(tmp_path)

    attachment = _upload(service, LAYOUT_CSV.encode("utf-8"))

    assert attachment.status == "ready"
    snapshot = service.temp_index_snapshot()
    document = next(iter(snapshot.documents))
    assert document.text == LAYOUT_CSV

    # What a citation would actually show: the chunk text, not the loader text.
    chunk_text = "".join(chunk.text for chunk in snapshot.chunks)
    assert chunk_text == document.text
    assert '"   "' in chunk_text
    assert "第一行\n\n第三行" in chunk_text


def test_csv_line_endings_are_preserved_as_data(tmp_path):
    service = _service(tmp_path)
    crlf = CSV_TEXT.replace("\n", "\r\n")

    attachment = _upload(service, crlf.encode("utf-8"))

    assert attachment.status == "ready"
    document = _indexed_documents(service)["counts.csv"]
    assert "\r\n" in document.text
    assert document.text == crlf


def test_csv_with_utf8_bom_drops_only_the_bom(tmp_path):
    service = _service(tmp_path)

    attachment = _upload(service, b"\xef\xbb\xbf" + CSV_TEXT.encode("utf-8"))

    assert attachment.status == "ready"
    document = _indexed_documents(service)["counts.csv"]
    assert not document.text.startswith("\ufeff")
    assert document.text == CSV_TEXT


def test_a_legal_field_larger_than_the_parser_default_is_indexed(tmp_path):
    service = _service(tmp_path)
    long_value = "x" * 200_000  # well past csv's ~128 KiB default field limit
    payload = f"id,notes\n1,{long_value}\n"

    attachment = _upload(service, payload.encode("utf-8"))

    assert attachment.status == "ready"
    document = _indexed_documents(service)["counts.csv"]
    assert long_value in document.text
    assert document.metadata["csv_rows"] == 2
    assert document.metadata["csv_columns"] == 2
    assert "csv_shape_error" not in document.metadata


def test_shape_metadata_failure_never_fails_the_attachment(tmp_path):
    service = _service(tmp_path)
    # Unterminated quote: the strict shape parser reports an error, while the
    # file itself is still usable text.
    payload = 'id,notes\n1,"unterminated\n'

    attachment = _upload(service, payload.encode("utf-8"))

    assert attachment.status == "ready"
    document = _indexed_documents(service)["counts.csv"]
    assert document.metadata["csv_rows"] is None
    assert document.metadata["csv_columns"] is None
    assert document.metadata["csv_has_header"] is None
    assert document.metadata["csv_shape_error"]
    assert payload == document.text


def test_csv_retrieval_is_scoped_to_its_thread(tmp_path):
    service = _service(tmp_path)
    _upload(service, CSV_TEXT.encode("utf-8"))

    own = service.retrieve_for_thread("gamma 900", "thread_csv")
    other = service.retrieve_for_thread("gamma 900", "thread_other")

    assert own, "the uploaded CSV must be retrievable inside its thread"
    assert any("900" in hit.chunk.text for hit in own)
    assert other == [], "another thread must never see the CSV"


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
