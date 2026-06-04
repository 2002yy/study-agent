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
        chunk_index = len(chunks)
        chunks.append(
            RagChunk(
                chunk_id=_chunk_hash(document.content_hash, chunk_index, text),
                document_hash=document.content_hash,
                source_path=document.source_path,
                title=document.title,
                text=text,
                chunk_index=chunk_index,
                start_line=current_start,
                end_line=current_end,
                metadata={
                    "file_type": document.file_type,
                    "char_count": len(text),
                },
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
            chunk_index = len(chunks)
            chunks.append(
                RagChunk(
                    chunk_id=_chunk_hash(document.content_hash, chunk_index, head),
                    document_hash=document.content_hash,
                    source_path=document.source_path,
                    title=document.title,
                    text=head,
                    chunk_index=chunk_index,
                    start_line=current_start,
                    end_line=current_end,
                    metadata={
                        "file_type": document.file_type,
                        "char_count": len(head),
                    },
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
