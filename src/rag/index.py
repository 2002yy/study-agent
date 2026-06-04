from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.rag.chunker import chunk_documents
from src.rag.loader import load_documents
from src.rag.schema import RagChunk, RagDocument, RagIndex, RagSearchResult
from src.safe_writer import safe_write_text

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RAG_INDEX_PATH = ROOT / "logs" / "rag_index.json"
INDEX_VERSION = 1


def _tokenize(text: str) -> list[str]:
    lowered = (text or "").lower()
    raw_tokens = re.findall(
        r"[a-z0-9]+(?:[_.+-][a-z0-9]+)*|[\u4e00-\u9fff]{2,}",
        lowered,
    )
    tokens: list[str] = []
    for token in raw_tokens:
        token = token.strip()
        if len(token) < 2:
            continue
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _document_frequency(chunks: tuple[RagChunk, ...]) -> Counter[str]:
    df: Counter[str] = Counter()
    for chunk in chunks:
        df.update(set(_tokenize(chunk.text)))
    return df


def _score_chunk(
    query: str,
    chunk: RagChunk,
    df: Counter[str],
    total_chunks: int,
) -> tuple[float, tuple[str, ...]]:
    query_terms = _tokenize(query)
    if not query_terms:
        return 0.0, ()

    chunk_terms = Counter(_tokenize(chunk.text))
    matched_terms: list[str] = []
    score = 0.0
    for term in query_terms:
        tf = chunk_terms.get(term, 0)
        if tf <= 0:
            continue
        matched_terms.append(term)
        idf = math.log((1 + total_chunks) / (1 + df.get(term, 0))) + 1.0
        score += (1.0 + math.log(tf)) * idf

    if not matched_terms:
        return 0.0, ()

    lowered_chunk = chunk.text.lower()
    lowered_query = query.lower().strip()
    if lowered_query and lowered_query in lowered_chunk:
        score += 2.0

    title_terms = set(_tokenize(chunk.title))
    if title_terms:
        score += 0.25 * len(set(matched_terms) & title_terms)

    return score, tuple(sorted(set(matched_terms)))


def _document_from_dict(data: dict[str, Any]) -> RagDocument:
    return RagDocument(
        source_path=str(data["source_path"]),
        title=str(data["title"]),
        text=str(data["text"]),
        content_hash=str(data["content_hash"]),
        file_type=str(data["file_type"]),
        metadata=dict(data.get("metadata") or {}),
    )


def _chunk_from_dict(data: dict[str, Any]) -> RagChunk:
    return RagChunk(
        chunk_id=str(data["chunk_id"]),
        document_hash=str(data["document_hash"]),
        source_path=str(data["source_path"]),
        title=str(data["title"]),
        text=str(data["text"]),
        chunk_index=int(data["chunk_index"]),
        start_line=int(data["start_line"]),
        end_line=int(data["end_line"]),
        metadata=dict(data.get("metadata") or {}),
    )


def build_rag_index(
    paths: Sequence[str | Path],
    *,
    max_chars: int = 900,
    overlap_chars: int = 120,
) -> RagIndex:
    documents = tuple(load_documents(paths))
    chunks = tuple(
        chunk_documents(
            list(documents),
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
    )
    return RagIndex(version=INDEX_VERSION, documents=documents, chunks=chunks)


def save_rag_index(
    index: RagIndex,
    path: str | Path = DEFAULT_RAG_INDEX_PATH,
) -> Path:
    target = Path(path)
    safe_write_text(target, json.dumps(index.to_dict(), ensure_ascii=False, indent=2))
    return target


def load_rag_index(path: str | Path = DEFAULT_RAG_INDEX_PATH) -> RagIndex:
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    return RagIndex(
        version=int(data.get("version", INDEX_VERSION)),
        documents=tuple(_document_from_dict(item) for item in data.get("documents", [])),
        chunks=tuple(_chunk_from_dict(item) for item in data.get("chunks", [])),
    )


def search_rag_index(
    index: RagIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.01,
) -> list[RagSearchResult]:
    if top_k <= 0:
        return []
    if not index.chunks:
        return []

    df = _document_frequency(index.chunks)
    scored: list[RagSearchResult] = []
    for chunk in index.chunks:
        score, matched_terms = _score_chunk(query, chunk, df, len(index.chunks))
        if score >= min_score:
            scored.append(
                RagSearchResult(
                    chunk=chunk,
                    score=round(score, 6),
                    matched_terms=matched_terms,
                )
            )

    scored.sort(key=lambda result: (-result.score, result.chunk.chunk_index, result.chunk.title))
    return scored[:top_k]
