from __future__ import annotations

from pathlib import Path

from src.rag import build_rag_index
from src.rag.source_coverage import (
    plan_source_coverage,
    search_documents_with_adaptive_source_coverage,
)


def test_source_coverage_plan_only_enables_for_explicit_composite_questions():
    normal = plan_source_coverage(
        "How does a requests Session reuse connections and handle timeouts?",
        top_k=4,
        configured_max_chunks_per_source=0,
    )
    combined = plan_source_coverage(
        "Which documents together explain the frontend simplification and committed learning truth?",
        top_k=4,
        configured_max_chunks_per_source=0,
    )
    while_clauses = plan_source_coverage(
        "How does the frontend stay simple while avoiding duplicated workflow truth?",
        top_k=4,
        configured_max_chunks_per_source=0,
    )
    between_clauses = plan_source_coverage(
        "What should happen between web research and the final answer?",
        top_k=4,
        configured_max_chunks_per_source=0,
    )
    chinese = plan_source_coverage(
        "中文资料问答如何同时保证召回和来源覆盖？",
        top_k=4,
        configured_max_chunks_per_source=0,
    )

    assert normal.enabled is False
    assert normal.effective_max_chunks_per_source == 0
    assert combined.enabled is True
    assert combined.reason == "together"
    assert combined.effective_max_chunks_per_source == 1
    assert combined.facet_top_k == 4
    assert while_clauses.enabled is True
    assert while_clauses.reason == "while_clauses"
    assert between_clauses.enabled is True
    assert between_clauses.reason == "between_clauses"
    assert chinese.enabled is True
    assert chinese.reason == "chinese_simultaneous"


def test_composite_query_uses_duplicate_slot_for_complementary_source(tmp_path):
    dominant = tmp_path / "dominant.md"
    supporting = tmp_path / "supporting.md"
    unrelated = tmp_path / "unrelated.md"
    dominant.write_text(
        "Frontend task selector simplification.\n\n"
        "Frontend task chip keeps the composer simple.\n\n"
        "Frontend controls hide the permanent selector.",
        encoding="utf-8",
    )
    supporting.write_text(
        "A returning learner restore card preserves committed learning truth and lets the learner continue where they stopped.",
        encoding="utf-8",
    )
    unrelated.write_text("Pasta sauce needs tomatoes.", encoding="utf-8")
    index = build_rag_index(
        [dominant, supporting, unrelated],
        max_chars=70,
        overlap_chars=0,
    )

    query = (
        "How do frontend task selector simplification and the restore card work together "
        "so the learner can continue where they stopped?"
    )
    diagnostics = search_documents_with_adaptive_source_coverage(
        index,
        query,
        retrieval_mode="hybrid",
        top_k=3,
    )
    names = [Path(result.chunk.source_path).name for result in diagnostics.results]

    assert diagnostics.debug["source_coverage"]["enabled"] is True
    assert diagnostics.debug["source_coverage"]["non_regression_rule"] == (
        "preserve_all_unique_base_sources"
    )
    assert names.count("dominant.md") <= 1
    assert "dominant.md" in names
    assert "supporting.md" in names


def test_adaptive_coverage_preserves_every_unique_source_from_base_top_k(tmp_path):
    primary = tmp_path / "primary.md"
    already_relevant = tmp_path / "already_relevant.md"
    complementary = tmp_path / "complementary.md"
    primary.write_text(
        "Task routing durable contract.\n\nTask routing retry contract.",
        encoding="utf-8",
    )
    already_relevant.write_text(
        "Frontend state is server owned and should not be duplicated locally.",
        encoding="utf-8",
    )
    complementary.write_text(
        "Restore card lets a returning learner continue where they stopped.",
        encoding="utf-8",
    )
    index = build_rag_index(
        [primary, already_relevant, complementary],
        max_chars=55,
        overlap_chars=0,
    )

    diagnostics = search_documents_with_adaptive_source_coverage(
        index,
        "How do durable task routing and the restore card work together so a learner can continue where they stopped?",
        retrieval_mode="hybrid",
        top_k=3,
    )
    names = [Path(result.chunk.source_path).name for result in diagnostics.results]

    assert "primary.md" in names
    assert "already_relevant.md" in names
    assert len(set(names)) == len(names)


def test_normal_question_preserves_existing_source_ranking_behavior(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text(
        "requests Session connection pooling\n\nrequests Session timeout behavior",
        encoding="utf-8",
    )
    second.write_text("unrelated cooking notes", encoding="utf-8")
    index = build_rag_index([first, second], max_chars=45, overlap_chars=0)

    diagnostics = search_documents_with_adaptive_source_coverage(
        index,
        "How does requests Session connection pooling work?",
        retrieval_mode="hybrid",
        top_k=2,
    )
    names = [Path(result.chunk.source_path).name for result in diagnostics.results]

    assert diagnostics.debug["source_coverage"]["enabled"] is False
    assert names[0] == "first.md"
