"""B-Search-2B8: feed-entry semantic selection and relevance refusal."""

from __future__ import annotations

from src.web.research.entry_selection import (  # noqa: E402
    assess_body,
    rank_entries,
    search_admission,
    select_entry,
)

ENTRIES = [
    {"title": "Python 3.14.1 is now available!", "url": "https://ex/314"},
    {"title": "Python 3.15.0 (final) is here!", "url": "https://ex/3150-final"},
    {"title": "Python 3.15.0 candidate 3 is here!", "url": "https://ex/3150-c3"},
    {"title": "A beginner tutorial: learn Python in an afternoon", "url": "https://ex/tut"},
]


def test_correct_answer_not_first():
    # The right entry is not index 0 and not the latest version.
    top = select_entry(ENTRIES, "Python 3.15.0 release announcement")
    assert top is not None and top["entry"]["url"] == "https://ex/3150-final"


def test_final_release_beats_prerelease():
    ranked = rank_entries(ENTRIES, "Python 3.15.0 正式发布说明")
    assert ranked[0]["entry"]["url"] == "https://ex/3150-final"
    candidate = next(r for r in ranked if r["entry"]["url"] == "https://ex/3150-c3")
    assert candidate["score"] < ranked[0]["score"]


def test_tutorial_request_rejects_release_post():
    # A release post must not satisfy a tutorial question when a tutorial exists.
    assert select_entry(ENTRIES, "Python 入门教程怎么学")["entry"]["url"] == "https://ex/tut"


def test_tutorial_request_without_tutorial_entry_is_refused():
    only_releases = [e for e in ENTRIES if "tutorial" not in e["title"]]
    assert select_entry(only_releases, "Python 入门教程") is None


def test_unrelated_question_is_refused():
    assert select_entry(ENTRIES, "围棋 提子 规则") is None


def test_weak_single_token_overlap_is_refused():
    assert select_entry(ENTRIES, "Python") is None


def test_version_does_not_bypass_tutorial_requirement():
    # "Python 3.15.0 入门教程" must NOT accept the versioned release post;
    # it must resolve to the tutorial entry (or refuse when no tutorial exists).
    top = select_entry(ENTRIES, "Python 3.15.0 入门教程")
    assert top is not None and "tutorial" in top["entry"]["title"]
    only_releases = [e for e in ENTRIES if "tutorial" not in e["title"]]
    assert select_entry(only_releases, "Python 3.15.0 入门教程") is None


def test_search_admission_refuses_explicit_type_conflict():
    assert search_admission("Python 3.15.0 downloads", "", "Python 3.15.0 入门教程")["decision"] == "refuse"


def test_search_admission_allows_thin_title_as_exploration():
    assert search_admission("Python 学习笔记", "", "Python 3.15.0 入门教程")["decision"] == "explore"


def test_search_admission_allows_likely_relevant():
    assert search_admission("Python 3.15.0 入门教程 (完整指南)", "", "Python 3.15.0 入门教程")["decision"] == "allow"


def test_assess_body_generic_tutorial_is_background_not_match():
    a = assess_body("Python tutorial for beginners. Variables, loops, Python is great.",
                    "Python 3.15.0 入门教程")
    assert a["verdict"] == "partial_background"
    assert any(m.startswith("version:") for m in a["missing"])


def test_assess_body_version_specific_matches():
    a = assess_body("This guide covers Python 3.15.0 tutorial steps and examples.",
                    "Python 3.15.0 入门教程")
    assert a["verdict"] == "matches"


def test_assess_body_unrelated_is_mismatch():
    assert assess_body("Go is a language.", "Python 3.15.0 入门教程")["verdict"] == "mismatch"
