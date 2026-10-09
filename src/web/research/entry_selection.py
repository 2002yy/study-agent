"""Feed-entry semantic selection (B-Search-2B8).

Deterministic, offline: rank feed entries against the user's full research goal
(topic + version + time + question type) and refuse when nothing matches. This is
an *exploratory relevance* judgement only — it never grants evidence support.
"""
from __future__ import annotations

import re

from src.web.research.source_directory import _terms

_VER = re.compile(r"\d+(?:\.\d+)+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_TUTORIAL = frozenset({"tutorial", "guide", "learn", "getting", "howto", "how", "教程", "入门", "指南"})
_RELEASE = frozenset({"release", "released", "available", "announcement", "announced", "发布", "正式", "可用"})
_PRERELEASE = frozenset({"candidate", "rc", "beta", "alpha", "preview", "prerelease", "pre-release"})
_FINAL = frozenset({"final", "stable", "released", "正式"})


def score_entry(title: str, question: str) -> tuple[int, list[str], list[str]]:
    """Return (score, reasons, notes) for one entry title vs the question.

    A typed request (tutorial/release) is not satisfied by topic overlap alone: if
    the question wants a tutorial or a specific release, the entry must match the
    type or the exact version, otherwise it scores 0 (a conservative refusal).
    """
    question_terms = _terms(question)
    title_terms = _terms(title)
    matched = sorted(question_terms & title_terms)
    reasons = [f"term:{t}" for t in matched]

    question_versions = set(_VER.findall(question))
    title_versions = set(_VER.findall(title))
    version_hit = bool(question_versions & title_versions)
    q_lower = question.casefold()
    t_lower = title.casefold()
    q_tut = {w for w in _TUTORIAL if w in q_lower}
    q_rel = {w for w in _RELEASE if w in q_lower}
    t_tut = {w for w in _TUTORIAL if w in t_lower}
    t_rel = {w for w in _RELEASE if w in t_lower}
    t_pre = {w for w in _PRERELEASE if w in t_lower}
    t_final = {w for w in _FINAL if w in t_lower}

    # A typed request must be satisfied by the SAME type family (or an exact
    # version); a release post does not answer a tutorial request and vice versa.
    # A tutorial request requires a tutorial entry (an exact version does NOT
    # substitute, e.g. "Python 3.15.0 入门教程" must not accept the release post);
    # a release request may be satisfied by an exact version.
    if q_tut and not t_tut:
        return 0, [], ["typed_request_unsatisfied"]
    if q_rel and not (t_rel or version_hit):
        return 0, [], ["typed_request_unsatisfied"]

    score = len(matched)
    if version_hit:
        score += 3
        reasons.append("version_exact:" + ",".join(sorted(question_versions & title_versions)))
    elif question_versions and title_versions:
        score -= 2  # a different version is a likely mismatch
        reasons.append("version_mismatch")
    if (q_tut and t_tut) or (q_rel and t_rel):
        score += 1
        reasons.append("type_match")
    if question_versions or q_rel:
        if t_pre:
            score -= 2
            reasons.append("prerelease")
        if t_final:
            score += 1
            reasons.append("final")
    return score, reasons, []


def rank_entries(entries: list[dict[str, str]], question: str) -> list[dict]:
    """Rank entries with a positive score, best first; each carries its reasons."""
    ranked: list[dict] = []
    for entry in entries:
        score, reasons, notes = score_entry(entry.get("title", ""), question)
        if score <= 0:
            ranked.append({"entry": entry, "score": score, "reasons": [], "excluded": notes[0] if notes else "no_match"})
            continue
        ranked.append({"entry": entry, "score": score, "reasons": reasons, "excluded": ""})
    ranked.sort(key=lambda row: (-row["score"], row["entry"].get("url", "")))
    return ranked


def select_entry(entries: list[dict[str, str]], question: str, *, min_score: int = 2) -> dict | None:
    """Return the best entry, or ``None`` => ``no_relevant_entry``.

    A weak single generic-token overlap (score < ``min_score``) is refused rather
    than reported as a match.
    """
    ranked = rank_entries(entries, question)
    top = ranked[0] if ranked else None
    if top and top["score"] >= min_score:
        return top
    return None
