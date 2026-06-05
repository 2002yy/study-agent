from __future__ import annotations

from src.rag import index_documents
from src.tools.local_knowledge import (
    NOT_FOUND_CONTEXT,
    retrieve_local_knowledge,
    rewrite_local_knowledge_query,
    should_retrieve_local_knowledge,
)


def test_local_knowledge_router_skips_conversation():
    should_retrieve, reason = should_retrieve_local_knowledge("你好")

    assert should_retrieve is False
    assert reason == "conversational_query"


def test_local_knowledge_router_detects_explicit_document_questions():
    should_retrieve, reason = should_retrieve_local_knowledge("请根据本地资料解释 RAG 架构")

    assert should_retrieve is True
    assert reason == "explicit_local_knowledge_hint"


def test_local_knowledge_rewrite_removes_instruction_boilerplate():
    rewritten = rewrite_local_knowledge_query("请根据本地资料回答：requests session reuse 是什么？")

    assert rewritten == "requests session reuse 是什么"


def test_retrieve_local_knowledge_skips_without_retrieval_signal(tmp_path):
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Local knowledge about retrieval.", encoding="utf-8")
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)

    result = retrieve_local_knowledge("hello", index_path=index_path)

    assert result.status == "skipped"
    assert result.attempted is False
    assert result.results == []


def test_retrieve_local_knowledge_finds_sources_with_explicit_hint(tmp_path):
    document = tmp_path / "requests.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text(
        "Python requests Session reuses HTTP connections for efficiency.",
        encoding="utf-8",
    )
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)

    result = retrieve_local_knowledge(
        "请根据本地资料解释 requests Session connections",
        index_path=index_path,
        top_k=1,
    )

    assert result.status == "found"
    assert result.retrieved is True
    assert len(result.results) == 1
    assert "requests.md" in result.sources
    assert "[1] requests" in result.context


def test_retrieve_local_knowledge_rewrites_weak_queries(tmp_path):
    document = tmp_path / "requests.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text(
        "Python requests Session reuse keeps HTTP connections warm.",
        encoding="utf-8",
    )
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)

    result = retrieve_local_knowledge(
        "请根据本地资料回答：requests Session reuse 是什么？",
        index_path=index_path,
        top_k=1,
        weak_score_threshold=999,
    )

    assert result.status == "found"
    assert result.rewritten_query == "requests Session reuse 是什么"
    assert [attempt.query for attempt in result.attempts] == [
        "请根据本地资料回答：requests Session reuse 是什么？",
        "requests Session reuse 是什么",
    ]


def test_retrieve_local_knowledge_not_found_returns_contract(tmp_path):
    document = tmp_path / "notes.md"
    index_path = tmp_path / "rag_index.json"
    document.write_text("Only contains local retrieval notes.", encoding="utf-8")
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)

    result = retrieve_local_knowledge(
        "请根据本地资料解释 quantum banana",
        index_path=index_path,
        top_k=1,
    )

    assert result.status == "not_found"
    assert result.context == NOT_FOUND_CONTEXT
    assert result.sources == ""
    assert result.attempted is True
