from __future__ import annotations

from src.rag import index_documents
from src.tools.local_knowledge import (
    INSUFFICIENT_CONTEXT,
    retrieve_local_knowledge,
)


def test_local_knowledge_returns_insufficient_without_exposing_candidate_results(tmp_path):
    document = tmp_path / "deployment.md"
    index_path = tmp_path / "rag-index.json"
    document.write_text(
        "Study Agent production model deployment requirements are documented at a high level.",
        encoding="utf-8",
    )
    index_documents([document], index_path=index_path, max_chars=300, overlap_chars=0)

    result = retrieve_local_knowledge(
        "请根据本地资料回答 Which exact NVIDIA GPU model is required for Study Agent production?",
        index_path=index_path,
        top_k=3,
    )

    assert result.status == "insufficient"
    assert result.retrieved is False
    assert result.results == []
    assert result.sources == ""
    assert result.context == INSUFFICIENT_CONTEXT
    assert result.debug["sufficiency"]["status"] == "insufficient"
    assert {"nvidia", "gpu"}.issubset(
        result.debug["sufficiency"]["absent_from_corpus_terms"]
    )
    # Candidate retrieval remains inspectable in debug rather than becoming evidence.
    assert result.debug["results"]


def test_local_knowledge_keeps_supported_material_available_to_answer(tmp_path):
    document = tmp_path / "requests.md"
    index_path = tmp_path / "rag-index.json"
    document.write_text(
        "Python requests Session reuses HTTP connections through a connection pool. Explicit timeouts remain necessary.",
        encoding="utf-8",
    )
    index_documents([document], index_path=index_path, max_chars=300, overlap_chars=0)

    result = retrieve_local_knowledge(
        "请根据本地资料解释 requests Session connections timeouts",
        index_path=index_path,
        top_k=3,
    )

    assert result.status == "found"
    assert result.retrieved is True
    assert result.results
    assert "requests.md" in result.sources
    assert result.debug["sufficiency"]["status"] == "supported"
