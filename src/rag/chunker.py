from __future__ import annotations

import hashlib

from src.rag.schema import RagChunk, RagDocument


def _chunk_hash(document_hash: str, chunk_index: int, text: str) -> str:
    raw = f"{document_hash}:{chunk_index}:{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _line_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    current_lines: list[str] = []
    current_start = 1

    for line_no, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not current_lines:
                current_start = line_no
            current_lines.append(line)
            continue

        if current_lines:
            spans.append(("\n".join(current_lines).strip(), current_start, line_no - 1))
            current_lines = []

    if current_lines:
        spans.append(
            (
                "\n".join(current_lines).strip(),
                current_start,
                current_start + len(current_lines) - 1,
            )
        )

    return spans


def _new_chunk(
    document: RagDocument,
    *,
    text: str,
    chunk_index: int,
    start_line: int,
    end_line: int,
) -> RagChunk:
    return RagChunk(
        chunk_id=_chunk_hash(document.content_hash, chunk_index, text),
        document_hash=document.content_hash,
        source_path=document.source_path,
        title=document.title,
        text=text,
        chunk_index=chunk_index,
        start_line=start_line,
        end_line=end_line,
        document_id=document.document_id,
        revision_id=document.revision_id,
        evidence_status=document.evidence_status,
        superseded_by_document_id=document.superseded_by_document_id,
        metadata={
            "file_type": document.file_type,
            "char_count": len(text),
        },
    )


def chunk_verbatim(
    document: RagDocument,
    *,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[RagChunk]:
    """Cut text into character windows without reflowing it.

    The paragraph path below strips each line, joins lines with ``\\n`` and drops
    blank lines - correct for prose, destructive for CSV where a trailing space
    or an empty line can be a field value. This path keeps every character and
    only decides where to cut.
    """

    text = document.text
    if not text:
        return []
    step = max_chars - overlap_chars
    if step <= 0:
        step = max_chars
    chunks: list[RagChunk] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        piece = text[start:end]
        start_line = text.count("\n", 0, start) + 1
        chunks.append(
            _new_chunk(
                document,
                text=piece,
                chunk_index=len(chunks),
                start_line=start_line,
                end_line=start_line + piece.count("\n"),
            )
        )
        if end >= len(text):
            break
        start += step
    return chunks


def chunk_document(
    document: RagDocument,
    *,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[RagChunk]:
    """Split a document into source-traceable chunks."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be non-negative")
    if document.file_type.lower() == "csv":
        return chunk_verbatim(
            document, max_chars=max_chars, overlap_chars=overlap_chars
        )
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    chunks: list[RagChunk] = []
    current_parts: list[str] = []
    current_start = 1
    current_end = 1

    def flush() -> None:
        nonlocal current_parts, current_start, current_end
        if not current_parts:
            return
        text = "\n\n".join(current_parts).strip()
        chunks.append(
            _new_chunk(
                document,
                text=text,
                chunk_index=len(chunks),
                start_line=current_start,
                end_line=current_end,
            )
        )

        if overlap_chars and len(text) > overlap_chars:
            overlap = text[-overlap_chars:].strip()
            current_parts = [overlap] if overlap else []
            current_start = current_end
        else:
            current_parts = []

    for paragraph, start_line, end_line in _line_spans(document.text):
        next_text = "\n\n".join([*current_parts, paragraph]).strip()
        if current_parts and len(next_text) > max_chars:
            flush()
        if not current_parts:
            current_start = start_line
        current_parts.append(paragraph)
        current_end = end_line

        while len("\n\n".join(current_parts)) > max_chars:
            text = "\n\n".join(current_parts).strip()
            head = text[:max_chars].strip()
            chunks.append(
                _new_chunk(
                    document,
                    text=head,
                    chunk_index=len(chunks),
                    start_line=current_start,
                    end_line=current_end,
                )
            )
            remainder_start = max(0, max_chars - overlap_chars)
            remainder = text[remainder_start:].strip()
            current_parts = [remainder] if remainder else []
            current_start = current_end

    flush()
    return chunks


def chunk_documents(
    documents: list[RagDocument],
    *,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> list[RagChunk]:
    chunks: list[RagChunk] = []
    for document in documents:
        chunks.extend(
            chunk_document(
                document,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        )
    return chunks
