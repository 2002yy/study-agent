from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_BATCH_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".markdown": {"text/markdown", "text/plain", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
}


@dataclass(frozen=True)
class UploadCandidate:
    filename: str
    content_type: str
    data: bytes


def validate_upload_batch(
    items: list[UploadCandidate],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_batch_bytes: int = DEFAULT_MAX_BATCH_BYTES,
) -> None:
    if not items:
        raise ValueError("At least one RAG document is required")
    total = sum(len(item.data) for item in items)
    if total > max_batch_bytes:
        raise ValueError(
            f"RAG upload batch is too large: {total} > {max_batch_bytes}"
        )
    for item in items:
        _validate_candidate(item, max_file_bytes=max_file_bytes)


def _validate_candidate(item: UploadCandidate, *, max_file_bytes: int) -> None:
    filename = Path(item.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_CONTENT_TYPES:
        raise ValueError(f"Unsupported RAG document type: {suffix or '<none>'}")
    size = len(item.data)
    if size <= 0:
        raise ValueError(f"RAG upload is empty: {filename}")
    if size > max_file_bytes:
        raise ValueError(f"RAG upload is too large: {filename}")
    content_type = (item.content_type or "application/octet-stream").lower()
    if content_type not in ALLOWED_CONTENT_TYPES[suffix]:
        raise ValueError(
            f"RAG upload MIME does not match {suffix}: {content_type}"
        )
    if suffix == ".pdf":
        if not item.data.startswith(b"%PDF-"):
            raise ValueError(f"Invalid PDF signature: {filename}")
        return
    if suffix == ".docx":
        _validate_docx(filename, item.data)
        return
    if b"\x00" in item.data:
        raise ValueError(f"Text upload contains binary NUL bytes: {filename}")
    try:
        item.data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Text upload must be UTF-8: {filename}") from exc


def _validate_docx(filename: str, data: bytes) -> None:
    if not data.startswith(b"PK"):
        raise ValueError(f"Invalid DOCX signature: {filename}")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            if (
                "[Content_Types].xml" not in names
                or "word/document.xml" not in names
            ):
                raise ValueError(f"Invalid DOCX structure: {filename}")
            total_uncompressed = sum(item.file_size for item in archive.infolist())
            if total_uncompressed > DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError(f"DOCX expands beyond safe limit: {filename}")
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid DOCX archive: {filename}") from exc
