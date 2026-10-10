"""P0-A narrow fix: one navigation family (doc versions) must not fill the display
slots. Regression uses the REAL saved PostgreSQL TOC candidate set."""
from __future__ import annotations

import json
from pathlib import Path

from src.web.link_discovery import (
    Candidate,
    diversify_navigation_families,
    question_terms,
    rank_candidates,
    version_family,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "postgres_toc_candidates.json"
CHAPTERS = ("mvcc-intro", "transaction-iso", "explicit-locking")


def _load() -> tuple[dict, list[Candidate]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    candidates = [
        Candidate(
            url=row["url"], anchor=row.get("anchor", ""), path=row.get("path", ""),
            context=row.get("context", ""), page_type=row.get("type", "uncertain"),
            score=float(row.get("score") or 0.0), why=row.get("why", ""),
        )
        for row in data["candidates"]
    ]
    return data, candidates


def _chapters(urls) -> set[str]:
    return {c for c in CHAPTERS if any(c in u for u in urls)}


def _docs_mvcc(urls) -> list[str]:
    """Only the docs chapter family — not comment/form URLs that merely end in mvcc.html."""
    return [u for u in urls if "/docs/" in u and "/mvcc.html" in u]


def test_fixture_records_the_pre_fix_display_defect():
    """The stored scores are the historical (defective) display: a wall of versions."""
    _data, candidates = _load()
    top = sorted(candidates, key=lambda c: (c.score, -c.order), reverse=True)[:10]
    urls = [c.url for c in top]
    assert sum(1 for u in urls if "/mvcc.html" in u) >= 5
    assert _chapters(urls) == set()


def test_chapters_reach_the_top10_after_display_diversity():
    data, candidates = _load()
    assert len(candidates) == 53
    ranked = rank_candidates(candidates, question_terms(data["question"]),
                             limit=10, question=data["question"])
    urls = [c.url for c in ranked]
    assert len(urls) == 10
    assert _chapters(urls), urls                       # a real chapter now has a slot
    assert len(_docs_mvcc(urls)) <= 1                  # versions no longer fill it


def test_named_version_is_kept_and_comparison_keeps_both():
    data, candidates = _load()
    terms = question_terms(data["question"])

    one = rank_candidates(candidates, terms, limit=10,
                          question="PostgreSQL 17 的 MVCC 如何避免阻塞？")
    kept = _docs_mvcc([c.url for c in one])
    assert kept and all("/17/" in u for u in kept), kept

    both = rank_candidates(candidates, terms, limit=10,
                           question="比较 PostgreSQL 17 与 18 的 MVCC 实现")
    kept = set(_docs_mvcc([c.url for c in both]))
    assert any("/17/" in u for u in kept) and any("/18/" in u for u in kept), kept


def test_diversity_never_adds_or_rewrites_urls():
    _data, candidates = _load()
    ranked = sorted(candidates, key=lambda c: (c.score, -c.order), reverse=True)
    kept = diversify_navigation_families(ranked, question="")
    original = {c.url for c in candidates}
    kept_urls = {c.url for c in kept}
    assert kept_urls <= original                                   # nothing added
    # it is a filter that preserves order, not a re-rank and not a rewrite
    assert [c.url for c in kept] == [c.url for c in ranked if c.url in kept_urls]


def test_small_families_are_untouched():
    _data, candidates = _load()
    ranked = sorted(candidates, key=lambda c: (c.score, -c.order), reverse=True)
    kept = {c.url for c in diversify_navigation_families(ranked, question="")}
    singles = [c.url for c in candidates if "textsearch-limitations" in c.url]
    assert singles and all(u in kept for u in singles)


def test_version_family_only_folds_doc_versions():
    family, token = version_family("https://www.postgresql.org/docs/17/mvcc.html")
    assert token == "17" and family and "*" in family
    # locale variants belong to the shared canonical_document helper, not this layer
    assert version_family("https://wiki.factorio.com/Logistic_network/zh") == ("", "")
