"""Page-intent inference and bounded query diversification (§36B slice 1).

§36A proved gap-aware keywords push discovery *deeper* but still not onto pages
that actually carry the target fact. §36B upgrades discovery from "search these
keywords" to "search this kind of page":

    gap -> infer evidence-bearing page type -> constrained discovery

This module is a small, deterministic taxonomy plus pure helpers. It never calls
a model, and its output is a **discovery hint only**: it must never reach
``relation``, ``strength``, or binding eligibility - those stay with the
extractor and the Evidence Gate.

Query variants are bounded and allocated inside the existing follow-up slots
(the budget is frozen): the point is to spend the same slots on different
queries instead of repeating one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.web.research.deeper_targeting import is_query_stopword

# --- bounded taxonomy ---------------------------------------------------------

# kind -> (match terms found in claim/missing-fact text, page-shape terms that
# usually appear in the path of a page carrying this kind of fact)
PAGE_INTENT_TAXONOMY: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "limit_policy": (
        (
            "limit",
            "limits",
            "rate",
            "rate-limit",
            "ratelimit",
            "quota",
            "throttle",
            "fair-use",
            "pull-rate",
            "usage",
        ),
        ("limits", "rate-limit", "usage", "policy", "fair-use"),
    ),
    "support_lifecycle": (
        (
            "support",
            "supported",
            "versioning",
            "lifecycle",
            "eol",
            "end-of-life",
            "maintained",
            "deprecat",
        ),
        ("support", "versioning", "lifecycle", "releases", "eol"),
    ),
    "feature_status": (
        (
            "status",
            "experimental",
            "stable",
            "preview",
            "free-threaded",
            "freethreaded",
            "threaded",
            "default",
            "enabled",
        ),
        ("whatsnew", "docs", "release-notes", "reference", "guide"),
    ),
    "spec_standard": (
        ("specification", "standard", "spec", "rfc", "pep", "normative"),
        ("spec", "specification", "pep", "rfc", "standard"),
    ),
    "api_reference": (
        ("api", "reference", "endpoint", "parameter", "argument", "schema"),
        ("api", "reference", "docs", "sdk"),
    ),
    "pricing_plan": (
        ("price", "pricing", "plan", "tier", "billing", "subscription"),
        ("pricing", "plans", "billing"),
    ),
    "security_advisory": (
        ("cve", "advisory", "vulnerability", "security", "disclosure", "exploit"),
        ("security", "advisories", "cve", "vulnerability"),
    ),
    "benchmark_performance": (
        ("benchmark", "throughput", "latency", "performance", "speed"),
        ("benchmarks", "performance", "benchmark"),
    ),
    "original_source": (
        (
            "original",
            "paper",
            "authors",
            "published",
            "first-hand",
            "upstream",
            "repository",
            "primary",
        ),
        ("abs", "pdf", "paper", "repo", "repository", "blob", "commit"),
    ),
}

INTENT_KIND_ORDER: tuple[str, ...] = tuple(PAGE_INTENT_TAXONOMY)

_AUTHORITATIVE_SOURCE_HINT = ("docs", "documentation")


@dataclass(frozen=True)
class PageIntent:
    """A discovery hint about the kind of page that would carry the fact."""

    kind: str
    path_terms: tuple[str, ...]
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path_terms": list(self.path_terms),
            "matched_terms": list(self.matched_terms),
        }


def _normalized_terms(values: Sequence[str]) -> tuple[str, ...]:
    terms: list[str] = []
    for value in values:
        clean = str(value).strip().casefold()
        if len(clean) < 3 or clean in terms:
            continue
        if is_query_stopword(clean):
            continue
        terms.append(clean)
    return tuple(terms)


def infer_page_intent(
    *,
    claim_terms: Sequence[str] = (),
    missing_fact_terms: Sequence[str] = (),
) -> PageIntent | None:
    """Pick the best-matching intent kind, deterministically.

    Scoring is pure term overlap over the bounded taxonomy; ties break by
    ``INTENT_KIND_ORDER`` so identical inputs always yield the same intent.
    """

    haystack = " ".join(
        (*_normalized_terms(claim_terms), *_normalized_terms(missing_fact_terms))
    )
    if not haystack:
        return None
    best: tuple[int, str] | None = None
    matched_by_kind: dict[str, tuple[str, ...]] = {}
    for kind in INTENT_KIND_ORDER:
        match_terms, _path_terms = PAGE_INTENT_TAXONOMY[kind]
        matched = tuple(term for term in match_terms if term in haystack)
        if not matched:
            continue
        matched_by_kind[kind] = matched
        score = len(matched)
        if best is None or score > best[0]:
            best = (score, kind)
    if best is None:
        return None
    kind = best[1]
    _match_terms, path_terms = PAGE_INTENT_TAXONOMY[kind]
    return PageIntent(
        kind=kind,
        path_terms=tuple(path_terms),
        matched_terms=matched_by_kind[kind],
    )


def query_variants(
    *,
    subject_terms: Sequence[str],
    missing_fact_terms: Sequence[str],
    intent: PageIntent | None,
    variant_limit: int = 3,
) -> tuple[str, ...]:
    """Bounded deterministic query variants (no negation, deduplicated, capped).

    Variant shapes follow §36B: subject+missing fact, +page intent, +authoritative
    source hint. The caller allocates these inside the existing follow-up slots,
    so total search budget never grows.
    """

    if variant_limit < 1:
        return ()
    base = list(_normalized_terms(subject_terms))[:3]
    gap_terms = [term for term in _normalized_terms(missing_fact_terms) if term not in base]
    if not base and not gap_terms:
        return ()

    variants: list[str] = []

    def _add(terms: Sequence[str]) -> None:
        if len(variants) >= variant_limit:
            return
        joined = " ".join(dict.fromkeys(term for term in terms if term))
        if joined and joined not in variants:
            variants.append(joined)

    _add([*base, *gap_terms])
    if intent is not None:
        _add([*base, *gap_terms, *intent.path_terms[:2]])
        _add([*base, *gap_terms, _AUTHORITATIVE_SOURCE_HINT[0]])
    else:
        _add([*base, *gap_terms, _AUTHORITATIVE_SOURCE_HINT[0]])
        _add([*base, *gap_terms, _AUTHORITATIVE_SOURCE_HINT[1]])
    return tuple(variants[:variant_limit])


def lexical_targeting_score(
    *,
    title: str,
    snippet: str,
    missing_fact_terms: Sequence[str],
    intent: PageIntent | None,
) -> dict[str, int]:
    """Missing-fact lexical coverage of a search result's title/snippet.

    Discovery ranking input only: it reports how many missing-fact and
    page-intent terms appear where a page usually announces its own subject.
    """

    title_folded = str(title or "").casefold()
    snippet_folded = str(snippet or "").casefold()
    gap_terms = _normalized_terms(missing_fact_terms)
    intent_terms = _normalized_terms(intent.path_terms) if intent is not None else ()
    title_match = sum(1 for term in gap_terms if term in title_folded)
    snippet_match = sum(1 for term in gap_terms if term in snippet_folded)
    intent_match = sum(
        1
        for term in intent_terms
        if term in title_folded or term in snippet_folded
    )
    return {
        "candidate_title_match": title_match,
        "candidate_snippet_match": snippet_match,
        "candidate_intent_match": intent_match,
    }


def targeting_preference_key(
    *,
    authoritative: bool,
    title_match: int,
    intent_match: int,
    snippet_match: int,
) -> tuple[int, int, int, int]:
    """Ascending sort key: authority first, then missing-fact lexical coverage.

    Authority deliberately outranks lexical overlap, so a tutorial/community page
    that merely repeats the words cannot displace an authoritative candidate; and
    a title that announces the missing fact outranks a snippet-only mention.
    """

    return (
        0 if authoritative else 1,
        -int(title_match),
        -int(intent_match),
        -int(snippet_match),
    )


def rank_search_results(
    rows: Sequence[Mapping[str, object]],
    *,
    missing_fact_terms: Sequence[str],
    intent: PageIntent | None,
    authoritative_urls: Sequence[str] = (),
) -> tuple[str, ...]:
    """Deterministic discovery ordering for search results (title/snippet aware).

    Discovery ranking only - it never marks a result as evidence, and it never
    decides ``relation`` or eligibility.
    """

    authoritative = {str(url) for url in authoritative_urls}
    scored: list[tuple[tuple[int, int, int, int], str]] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        lexical = lexical_targeting_score(
            title=str(row.get("title") or ""),
            snippet=str(row.get("snippet") or ""),
            missing_fact_terms=missing_fact_terms,
            intent=intent,
        )
        key = targeting_preference_key(
            authoritative=url in authoritative,
            title_match=lexical["candidate_title_match"],
            intent_match=lexical["candidate_intent_match"],
            snippet_match=lexical["candidate_snippet_match"],
        )
        scored.append((key, url))
    scored.sort(key=lambda item: (item[0], item[1]))
    return tuple(url for _key, url in scored)


def selection_reason(
    *,
    authoritative: bool,
    title_match: int,
    intent_match: int,
) -> str:
    """Short audit label for why a candidate was preferred (diagnostic only)."""

    parts: list[str] = []
    if authoritative:
        parts.append("authority")
    if title_match:
        parts.append("missing_fact_title_match")
    if intent_match:
        parts.append("page_intent_match")
    return "+".join(parts) if parts else "fallback_order"
