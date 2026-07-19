from __future__ import annotations

from src.rag import build_rag_index
from src.rag.schema import RagSearchResult
from src.rag.service import search_documents
from src.rag.sufficiency import assess_evidence_sufficiency, informative_query_terms


def test_evidence_sufficiency_accepts_well_covered_local_answer(tmp_path):
    document = tmp_path / "requests.md"
    document.write_text(
        "Python requests Session reuses connection pools. Explicit timeouts and retry limits still matter.",
        encoding="utf-8",
    )
    index = build_rag_index([document], max_chars=300, overlap_chars=0)
    results = search_documents(
        index,
        "How does requests Session reuse connections and why do explicit timeouts still matter?",
        retrieval_mode="hybrid",
        top_k=3,
    )

    decision = assess_evidence_sufficiency(index, "requests Session connections explicit timeouts", results)

    assert decision.status == "supported"
    assert decision.reason == "no_high_confidence_insufficiency_signal"
    assert decision.allows_grounded_answer is True
    assert decision.missing_hard_anchor_terms == ()
    assert {"requests", "session", "timeouts"}.issubset(decision.covered_terms)


def test_evidence_sufficiency_blocks_related_text_when_explicit_hard_anchors_are_absent(tmp_path):
    document = tmp_path / "deployment.md"
    document.write_text(
        "Study Agent production model deployment requirements are documented at a high level.",
        encoding="utf-8",
    )
    index = build_rag_index([document], max_chars=300, overlap_chars=0)
    chunk = index.chunks[0]
    related_result = RagSearchResult(chunk=chunk, score=0.03, matched_terms=("model", "production"))

    decision = assess_evidence_sufficiency(
        index,
        "Which exact NVIDIA GPU model is required for Study Agent production?",
        [related_result],
    )

    assert decision.status == "insufficient"
    assert decision.reason == "missing_explicit_anchor_concepts"
    assert decision.hard_anchor_terms == ("nvidia", "gpu")
    assert decision.missing_hard_anchor_terms == ("nvidia", "gpu")
    assert {"nvidia", "gpu"}.issubset(decision.absent_from_corpus_terms)
    assert decision.allows_grounded_answer is False


def test_evidence_sufficiency_uses_cjk_bigrams_instead_of_sentence_sized_absent_tokens(tmp_path):
    document = tmp_path / "cn.md"
    document.write_text(
        "中文资料问答使用混合检索，并且最终回答需要保留来源引用。",
        encoding="utf-8",
    )
    index = build_rag_index([document], max_chars=300, overlap_chars=0)
    results = search_documents(
        index,
        "中文资料如何使用混合检索并保留来源引用",
        retrieval_mode="hybrid",
        top_k=3,
    )

    terms = informative_query_terms("中文资料如何使用混合检索并保留来源引用")
    decision = assess_evidence_sufficiency(
        index,
        "中文资料如何使用混合检索并保留来源引用",
        results,
    )

    assert terms
    assert all(len(term) == 2 for term in terms)
    assert decision.status == "supported"
