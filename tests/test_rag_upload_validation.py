import io
import zipfile

import pytest

from src.rag.upload_validation import (
    UploadCandidate,
    validate_upload_batch,
)


def test_upload_batch_rejects_aggregate_size():
    items = [
        UploadCandidate("a.txt", "text/plain", b"a" * 6),
        UploadCandidate("b.txt", "text/plain", b"b" * 6),
    ]
    with pytest.raises(ValueError, match="batch is too large"):
        validate_upload_batch(items, max_file_bytes=10, max_batch_bytes=10)


def test_upload_rejects_mime_and_magic_mismatch():
    with pytest.raises(ValueError, match="MIME"):
        validate_upload_batch(
            [UploadCandidate("notes.txt", "application/pdf", b"plain text")]
        )
    with pytest.raises(ValueError, match="PDF signature"):
        validate_upload_batch(
            [UploadCandidate("fake.pdf", "application/pdf", b"not a pdf")]
        )


def test_docx_requires_office_structure():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("random.txt", "not a Word document")
    with pytest.raises(ValueError, match="DOCX structure"):
        validate_upload_batch(
            [
                UploadCandidate(
                    "fake.docx",
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document",
                    output.getvalue(),
                )
            ]
        )
