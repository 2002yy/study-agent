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


MIN_SCORE = 2


def select_entry(entries: list[dict[str, str]], question: str, *, min_score: int = MIN_SCORE) -> dict | None:
    """Return the best entry, or ``None`` => ``no_relevant_entry``.

    A weak single generic-token overlap (score < ``min_score``) is refused rather
    than reported as a match.
    """
    ranked = rank_entries(entries, question)
    top = ranked[0] if ranked else None
    if top and top["score"] >= min_score:
        return top
    return None


def admission_map(entries: list[dict[str, str]], question: str, *,
                  min_score: int = MIN_SCORE) -> dict[str, str]:
    """Map each entry URL -> ``""`` (eligible) or an exclusion reason for this question.

    ``admission_map`` is the *tool-layer* form of :func:`select_entry`: it keeps the
    full eligibility picture so a caller can refuse to READ an entry that is excluded
    for the current goal (even if the URL was discovered elsewhere).
    """
    out: dict[str, str] = {}
    for row in rank_entries(entries, question):
        url = row["entry"].get("url", "")
        if not url:
            continue
        if row["excluded"]:
            out[url] = row["excluded"]
        elif row["score"] < min_score:
            out[url] = "below_threshold"
        else:
            out[url] = ""
    return out


_DOWNLOAD = frozenset({"download", "downloads", "install"})


def search_admission(title: str, snippet: str, question: str) -> dict:
    """Source-type-aware admission for a SEARCH result (title + snippet only).

    Unlike feed entries, search results are NOT held to the fixed threshold: a thin
    title ("Python 学习笔记") is allowed as **exploration** so a genuinely relevant body
    is not missed. Only an *explicit* goal conflict is refused before reading:
    a clearly wrong content type (release/download page for a tutorial request, or a
    tutorial for a release request) or a title carrying a *different* demanded version.
    """
    score, _reasons, _notes = score_entry(title, question)
    q_lower = question.casefold()
    t_lower = title.casefold()
    q_tut = {w for w in _TUTORIAL if w in q_lower}
    q_rel = {w for w in _RELEASE if w in q_lower}
    t_tut = {w for w in _TUTORIAL if w in t_lower}
    t_rel = {w for w in _RELEASE if w in t_lower}
    t_dl = {w for w in _DOWNLOAD if w in t_lower}
    q_ver = set(_VER.findall(question))
    t_ver = set(_VER.findall(title))
    if q_tut and not t_tut and (t_rel or t_dl):
        return {"decision": "refuse", "reason": "type_conflict", "score": score}
    if q_rel and not t_rel and (t_tut or t_dl):
        return {"decision": "refuse", "reason": "type_conflict", "score": score}
    if q_ver and t_ver and not (q_ver & t_ver):
        return {"decision": "refuse", "reason": "version_conflict", "score": score}
    if score >= MIN_SCORE:
        return {"decision": "allow", "reason": "likely_relevant", "score": score}
    return {"decision": "explore", "reason": "insufficient_information", "score": score}


def assess_body(content: str, question: str) -> dict:
    """Post-read goal match (relevance only — never evidence).

    Returns ``verdict`` in {matches, partial_background, mismatch, insufficient_information}
    plus the goal conditions met/missing, with a body snippet for locating the basis.
    """
    low = content.casefold()
    terms = _terms(question)
    hits = [t for t in terms if t in low]
    q_ver = set(_VER.findall(question))
    version_ok = any(v in low for v in q_ver) if q_ver else None
    snippet = ""
    for t in hits:
        i = low.find(t)
        if i >= 0:
            snippet = content[max(0, i - 40):i + 80]
            break
    if not hits:
        return {"verdict": "mismatch", "met": [], "missing": [], "basis": ""}
    if q_ver and not version_ok:
        return {"verdict": "partial_background", "met": hits,
                "missing": ["version:" + v for v in sorted(q_ver)], "basis": snippet}
    if len(hits) >= 2:
        return {"verdict": "matches", "met": hits, "missing": [], "basis": snippet}
    return {"verdict": "insufficient_information", "met": hits, "missing": [], "basis": snippet}
