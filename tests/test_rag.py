from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from src.rag import build_rag_context, format_rag_sources, index_documents, query_documents
from src.rag.chunker import chunk_document
from src.rag.index import build_rag_index, load_rag_index, search_rag_index
from src.rag.loader import load_document
from src.rag.vector import cosine_similarity, embed_text, search_rag_index_hybrid, search_rag_index_vector
from src.ui.rag_panel import parse_path_lines, sanitize_upload_name


def _install_fake_pypdf(
    monkeypatch,
    *,
    pages: list[str],
    encrypted: bool = False,
) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self) -> str:
            return self._text

    class FakeReader:
        def __init__(self, _path: str) -> None:
            self.is_encrypted = encrypted
            self.pages = [FakePage(text) for text in pages]

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=FakeReader))


def test_load_markdown_document_normalizes_text_and_metadata(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("  RAG notes  \r\n\r\nretrieval budget  \n", encoding="utf-8")

    document = load_document(path)

    assert document.title == "notes"
    assert document.file_type == "md"
    assert document.text == "RAG notes\n\nretrieval budget"
    assert document.metadata["size_bytes"] > 0
    assert len(document.content_hash) == 64


def test_load_docx_document_when_python_docx_is_available(tmp_path):
    from docx import Document

    path = tmp_path / "lesson.docx"
    document = Document()
    document.add_paragraph("Session memory")
    document.add_paragraph("Citation retrieval")
    document.save(path)

    loaded = load_document(path)

    assert loaded.file_type == "docx"
    assert "Session memory" in loaded.text
    assert "Citation retrieval" in loaded.text


def test_load_pdf_document_extracts_page_text_and_metadata(tmp_path, monkeypatch):
    _install_fake_pypdf(monkeypatch, pages=["PDF retrieval text", "second page"])
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4")

    document = load_document(path)

    assert document.file_type == "pdf"
    assert "[Page 1]" in document.text
    assert "PDF retrieval text" in document.text
    assert document.metadata["pdf_pages"] == 2


def test_pdf_loader_rejects_oversized_files(tmp_path):
    path = tmp_path / "large.pdf"
    path.write_bytes(b"%PDF-1.4 large")

    with pytest.raises(ValueError, match="PDF is too large"):
        load_document(path, max_pdf_bytes=4)


def test_pdf_loader_rejects_too_many_pages(tmp_path, monkeypatch):
    _install_fake_pypdf(monkeypatch, pages=["one", "two", "three"])
    path = tmp_path / "many_pages.pdf"
    path.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="PDF has too many pages"):
        load_document(path, max_pdf_pages=2)


def test_pdf_loader_rejects_encrypted_files(tmp_path, monkeypatch):
    _install_fake_pypdf(monkeypatch, pages=["secret"], encrypted=True)
    path = tmp_path / "encrypted.pdf"
    path.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="Encrypted PDF"):
        load_document(path)


def test_chunk_document_tracks_source_lines(tmp_path):
    path = tmp_path / "source.md"
    path.write_text("Intro line\nSecond line\n\nBudget line\n", encoding="utf-8")
    document = load_document(path)

    chunks = chunk_document(document, max_chars=200, overlap_chars=0)

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 4
    assert chunks[0].metadata["char_count"] == len(chunks[0].text)


def test_build_save_load_and_query_rag_index(tmp_path):
    python_doc = tmp_path / "python.md"
    cooking_doc = tmp_path / "cooking.txt"
    python_doc.write_text("Python requests sessions reuse connections.", encoding="utf-8")
    cooking_doc.write_text("Pasta sauce needs tomatoes.", encoding="utf-8")
    index_path = tmp_path / "rag_index.json"

    index = index_documents(
        [python_doc, cooking_doc],
        index_path=index_path,
        max_chars=200,
        overlap_chars=0,
    )
    loaded = load_rag_index(index_path)
    results = query_documents("requests sessions", index_path=index_path, top_k=1)

    assert len(index.documents) == 2
    assert len(loaded.chunks) == 2
    assert results[0].chunk.source_path == str(python_doc)
    assert results[0].matched_terms == ("requests", "sessions")

    raw_index = json.loads(index_path.read_text(encoding="utf-8"))
    assert raw_index["version"] == 1


def test_chinese_query_matches_cjk_bigrams(tmp_path):
    path = tmp_path / "cn.md"
    path.write_text(
        "\u5411\u91cf\u68c0\u7d22\u5e2e\u52a9\u672c\u5730\u77e5\u8bc6\u95ee\u7b54",
        encoding="utf-8",
    )

    index = build_rag_index([path], max_chars=200, overlap_chars=0)
    results = search_rag_index(index, "\u5411\u91cf", top_k=1)

    assert results
    assert "\u5411\u91cf" in results[0].matched_terms


def test_vector_retrieval_ranks_matching_chunk(tmp_path):
    python_doc = tmp_path / "python.md"
    cooking_doc = tmp_path / "cooking.md"
    python_doc.write_text("HTTP requests sessions reuse connections.", encoding="utf-8")
    cooking_doc.write_text("Tomato pasta sauce needs basil.", encoding="utf-8")
    index = build_rag_index([python_doc, cooking_doc], max_chars=200, overlap_chars=0)

    results = search_rag_index_vector(index, "requests connections", top_k=1)

    assert results[0].chunk.source_path == str(python_doc)
    assert 0 < results[0].score <= 1
    assert "connections" in results[0].matched_terms


def test_hybrid_retrieval_combines_lexical_and_vector_scores(tmp_path):
    python_doc = tmp_path / "python.md"
    cooking_doc = tmp_path / "cooking.md"
    python_doc.write_text("HTTP requests sessions reuse connections.", encoding="utf-8")
    cooking_doc.write_text("Tomato pasta sauce needs basil.", encoding="utf-8")
    index = build_rag_index([python_doc, cooking_doc], max_chars=200, overlap_chars=0)

    results = search_rag_index_hybrid(index, "requests connections", top_k=1)

    assert results[0].chunk.source_path == str(python_doc)
    assert "requests" in results[0].matched_terms


def test_query_documents_supports_retrieval_modes(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Local vector retrieval keeps cited chunks.", encoding="utf-8")
    index_path = tmp_path / "rag_index.json"
    index_documents([path], index_path=index_path, max_chars=200, overlap_chars=0)

    lexical_results = query_documents("cited chunks", index_path=index_path, retrieval_mode="lexical")
    hybrid_results = query_documents("cited chunks", index_path=index_path, retrieval_mode="hybrid")
    vector_results = query_documents("cited chunks", index_path=index_path, retrieval_mode="vector")

    assert lexical_results
    assert hybrid_results
    assert vector_results


def test_query_documents_rejects_unknown_retrieval_mode(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Local retrieval.", encoding="utf-8")
    index_path = tmp_path / "rag_index.json"
    index_documents([path], index_path=index_path, max_chars=200, overlap_chars=0)

    with pytest.raises(ValueError, match="Unsupported RAG retrieval mode"):
        query_documents("retrieval", index_path=index_path, retrieval_mode="semantic")


def test_local_hash_embeddings_are_deterministic():
    left = embed_text("requests session reuse")
    right = embed_text("requests session reuse")

    assert left == right
    assert cosine_similarity(left, right) == pytest.approx(1.0)


def test_build_rag_context_includes_citations_and_limits_text(tmp_path):
    path = tmp_path / "architecture.md"
    path.write_text("RAG architecture uses cited chunks for answers.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)
    results = search_rag_index(index, "cited chunks", top_k=1)

    context = build_rag_context(results, max_chars=500)

    assert "[1] architecture" in context
    assert f"{path}:L1-L1" in context
    assert "cited chunks" in context
    assert len(context) <= 500


def test_format_rag_sources_lists_file_lines_and_terms(tmp_path):
    path = tmp_path / "architecture.md"
    path.write_text("RAG architecture uses cited chunks for answers.", encoding="utf-8")
    index = build_rag_index([path], max_chars=200, overlap_chars=0)
    results = search_rag_index(index, "cited chunks", top_k=1)

    source_block = format_rag_sources(results)

    assert "[1] architecture" in source_block
    assert f"{path}:L1-L1" in source_block
    assert "matched=chunks, cited" in source_block


def test_empty_rag_context_is_explicit():
    assert build_rag_context([]) == "No relevant local documents retrieved."


def test_empty_rag_sources_are_blank():
    assert format_rag_sources([]) == ""


def test_rag_upload_name_is_sanitized():
    assert sanitize_upload_name("../unsafe lesson.md") == "unsafe_lesson.md"
    assert sanitize_upload_name("资料 01.docx") == "01.docx"
    assert sanitize_upload_name("...") == "document"


def test_parse_path_lines_ignores_blank_lines():
    paths = parse_path_lines(' "notes.md" \n\n C:/tmp/lesson.txt ')

    normalized = [str(path).replace("\\", "/") for path in paths]
    assert normalized == ["notes.md", "C:/tmp/lesson.txt"]
