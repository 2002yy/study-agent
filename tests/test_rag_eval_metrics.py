from __future__ import annotations

from src.rag.eval import _ndcg_at_k


def test_source_ndcg_does_not_double_count_duplicate_chunks():
    score = _ndcg_at_k(
        (
            "notes/a.md",
            "notes/a.md",
            "notes/b.md",
        ),
        ("a.md",),
        3,
    )

    assert score == 1.0


def test_duplicate_chunk_still_consumes_rank_position_for_later_relevant_source():
    score = _ndcg_at_k(
        (
            "notes/a.md",
            "notes/a.md",
            "notes/b.md",
        ),
        ("a.md", "b.md"),
        3,
    )

    assert 0.0 < score < 1.0
