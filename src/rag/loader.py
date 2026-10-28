from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.rag.schema import RagDocument

SUPPORTED_TEXT_EXTENSIONS = {".md", ".markdown", ".txt", ".csv"}
SUPPORTED_EXTENSIONS = SUPPORTED_TEXT_EXTENSIONS | {".docx", ".pdf"}
DEFAULT_MAX_PDF_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_PDF_PAGES = 30
DEFAULT_MAX_PDF_CHARS = 120_000
# Above the 20 MiB attachment ceiling, so a legal CSV never fails on a field.
CSV_FIELD_LIMIT = 32 * 1024 * 1024


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_document_id(source: Path) -> str:
    identity = source.resolve().as_posix().casefold()
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _normalize_text(text: str) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    paragraphs: list[str] = []
    blank_seen = False
    for line in lines:
        if line.strip():
            paragraphs.append(line)
            blank_seen = False
        elif paragraphs and not blank_seen:
            paragraphs.append("")
            blank_seen = True
    return "\n".join(paragraphs).strip()


def _read_text_path(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_csv_path(path: Path) -> str:
    """Read a UTF-8 CSV as plain text, keeping the header and every data row.

    This is deliberately not a spreadsheet parser. The rows are indexed as text
    so a question about the file can cite the original values. A UTF-8 BOM is
    tolerated because common spreadsheet exports write one; NUL bytes and
    non-UTF-8 bytes are rejected instead of being silently turned into mojibake.
    """

    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError(f"CSV contains NUL bytes: {path}")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"CSV must be UTF-8 encoded: {path}") from exc


def _csv_shape(text: str) -> dict[str, Any]:
    """Row/column counts for evidence, without interpreting cell types.

    The shape is *optional* metadata: a legal CSV with an unusually large field
    must still be indexed, so a parser failure here is recorded rather than
    raised. ``csv_has_header`` stays ``None`` because nothing in a CSV file
    proves its first row is a header; claiming otherwise would be an invented
    fact. ``csv_rows`` counts records and may therefore include a header row.
    """

    import csv
    import io

    previous_limit = csv.field_size_limit()
    try:
        # The attachment ceiling is 20 MiB; the parser default (~128 KiB per
        # field) would reject files this product accepts.
        csv.field_size_limit(max(previous_limit, CSV_FIELD_LIMIT))
    except (OverflowError, ValueError):
        pass
    rows = 0
    columns = 0
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        for row in reader:
            if not row:
                continue
            rows += 1
            columns = max(columns, len(row))
    except csv.Error as exc:
        return {
            "csv_rows": None,
            "csv_columns": None,
            "csv_has_header": None,
            "csv_shape_error": str(exc)[:200],
        }
    finally:
        csv.field_size_limit(previous_limit)
    return {"csv_rows": rows, "csv_columns": columns, "csv_has_header": None}


def _read_docx_path(path: Path) -> str:
    try:
        from docx import Document
    except Exception as exc:
        raise RuntimeError("python-docx is required to load .docx files") from exc

    document = Document(str(path))
    parts = [paragraph.text.strip() for paragraph in document.paragraphs]
    return "\n\n".join(part for part in parts if part)


def _read_pdf_path(
    path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_PDF_BYTES,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_chars: int = DEFAULT_MAX_PDF_CHARS,
) -> tuple[str, dict[str, Any]]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if path.stat().st_size > max_bytes:
        raise ValueError(f"PDF is too large: {path}")

    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError("pypdf is required to load .pdf files") from exc

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise ValueError(f"Encrypted PDF is not supported: {path}")
    page_count = len(reader.pages)
    if page_count > max_pages:
        raise ValueError(f"PDF has too many pages: {page_count} > {max_pages}")

    parts: list[str] = []
    page_map: list[dict[str, int]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            start_line = (
                len(_normalize_text("\n\n".join(parts)).splitlines()) + 2
                if parts
                else 1
            )
            page_map.append({"page": page_index, "line": start_line})
            parts.append(f"[Page {page_index}]\n{text.strip()}")
        if sum(len(part) for part in parts) > max_chars:
            raise ValueError(f"PDF extracted text is too long: {path}")

    return "\n\n".join(parts), {"pdf_pages": page_count, "pdf_page_map": page_map}


def load_document(
    path: str | Path,
    *,
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES,
    max_pdf_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_pdf_chars: int = DEFAULT_MAX_PDF_CHARS,
) -> RagDocument:
    """Load one local document into a normalized RAG document."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(str(source))

    suffix = source.suffix.lower()
    loader_metadata: dict[str, Any] = {}
    if suffix == ".csv":
        # CSV cells are data: a trailing space or an empty line may be a value.
        # The decoded text is therefore indexed verbatim; only chunking decides
        # where it is cut (see ``chunk_verbatim``).
        text = _read_csv_path(source)
        loader_metadata = _csv_shape(text)
    elif suffix in SUPPORTED_TEXT_EXTENSIONS:
        text = _normalize_text(_read_text_path(source))
    elif suffix == ".docx":
        text = _normalize_text(_read_docx_path(source))
    elif suffix == ".pdf":
        raw_text, loader_metadata = _read_pdf_path(
            source,
            max_bytes=max_pdf_bytes,
            max_pages=max_pdf_pages,
            max_chars=max_pdf_chars,
        )
        text = _normalize_text(raw_text)
    else:
        raise ValueError(f"Unsupported RAG document type: {suffix or '<none>'}")

    if not text.strip():
        raise ValueError(f"RAG document is empty: {source}")

    stat = source.stat()
    document_id = _stable_document_id(source)
    content_hash = _sha256_text(text)
    parser_version = "loader_v1"
    return RagDocument(
        source_path=str(source),
        title=source.stem,
        text=text,
        content_hash=content_hash,
        file_type=suffix.lstrip("."),
        document_id=document_id,
        revision_id=_sha256_text(f"{document_id}:{content_hash}:{parser_version}")[:24],
        parser_version=parser_version,
        metadata={
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            **(
                {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
                if suffix in {".pdf", ".csv"}
                else {}
            ),
            **loader_metadata,
        },
    )


def load_documents(paths: Sequence[str | Path]) -> list[RagDocument]:
    return [load_document(path) for path in paths]
