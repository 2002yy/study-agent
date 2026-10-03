"""Gap-aware deeper-page targeting for discovery (PROJECT_STATUS §36A).

The Support Formation Audit (§35) showed why real runs end with
``relation="lead"``: the *pages* are wrong (homepages, landing pages, mirrors,
tutorials), while the extractor is right when it says "this page does not
contain the target fact". This module turns the extractor's own gap statement
into a positive discovery target, and orders discovery candidates so that
authoritative deep pages beat root/landing/mirror pages.

Boundaries (frozen by §36A):

* ranking only - this module never decides ``relation``, ``strength`` or
  binding eligibility; those stay with the extractor and the Evidence Gate;
* only ``lead`` / ``qualifies`` rows with usable anchors/locator and a caveat
  trigger targeting; ``supports`` and ``background`` never do;
* the follow-up query is built from the *missing fact* in positive form; the raw
  caveat sentence (which is a negation) is never searched for;
* same-domain affinity is a strong signal only when the source page itself is
  authoritative.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

# --- authority classes --------------------------------------------------------

AUTHORITY_OFFICIAL = "official"
AUTHORITY_MIRROR = "mirror"
AUTHORITY_TUTORIAL = "tutorial"
AUTHORITY_COMMUNITY = "community"
AUTHORITY_UNKNOWN = "unknown"

_TUTORIAL_HOSTS = (
    "runoob.com",
    "w3schools.com",
    "tutorialspoint.com",
    "javatpoint.com",
    "geeksforgeeks.org",
    "csdn.net",
    "cnblogs.com",
    "jianshu.com",
    "juejin.cn",
    "zhihu.com",
    "bilibili.com",
)
_MIRROR_HOSTS = (
    "github.net.cn",
    "gitee.com",
    "gitcode.com",
    "gitcode.net",
    "hub.fastgit.org",
    "docker.github.net.cn",
    "aliyun.com",
    "163.com",
    "sohu.com",
    "sina.com.cn",
    "medium.com",
    "dev.to",
)
# Target-shaped paths are the pages that usually carry the actual fact.
_TARGET_PATH_TOKENS = (
    "/docs",
    "/doc/",
    "/documentation",
    "/reference",
    "/api/",
    "/policy",
    "/policies",
    "/support",
    "/supported",
    "/release",
    "/releases",
    "/changelog",
    "/limits",
    "/rate-limit",
    "/ratelimit",
    "/spec",
    "/specification",
    "/pep/",
    "/guide",
    "/manual",
    "/security",
    "/license",
    "/eol",
    "/lifecycle",
)

# Caveat clauses that say "the fact is not here"; the *object* after them is the
# positive search target.
_ABSENCE_PATTERNS = (
    r"does not (?:mention|state|specify|include|provide|contain|list|describe|enumerate|discuss|address|give|report)[^.]*?",
    r"contains no[^.]*?",
    r"has no[^.]*?",
    r"only (?:mentions|states|lists|shows|describes|references)[^.]*?",
    r"not explicitly[^.]*?",
)
_NEGATION_TOKENS = {
    "not",
    "no",
    "does",
    "do",
    "doesn",
    "doesnt",
    "without",
    "never",
    "cannot",
    "isn",
    "isnt",
    "only",
    "explicitly",
    "mention",
    "mentions",
    "mentioning",
    "state",
    "states",
    "stated",
    "specify",
    "specifies",
    "include",
    "includes",
    "provide",
    "provides",
    "contain",
    "contains",
    "list",
    "lists",
    "describe",
    "describes",
    "enumerate",
    "enumerates",
    "discuss",
    "discusses",
    "address",
    "addresses",
    "give",
    "gives",
    "report",
    "reports",
    "the",
    "a",
    "an",
    "any",
    "this",
    "that",
    "which",
    "their",
    "its",
    "page",
    "document",
    "does",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "of",
    "for",
    "to",
    "in",
    "on",
    "at",
    "or",
    "and",
    "but",
    "with",
    "about",
    "from",
    "by",
    # Weak fillers that would pollute a targeted query.
    "itself",
    "excerpt",
    "excerpts",
    "sentence",
    "sentences",
    "content",
    "text",
    "anything",
    "something",
}
_MIN_LOCATOR_CHARS = 12
_MAX_QUERY_TERMS = 6
_MAX_CLAIM_TERMS = 3

# Common multi-label public suffixes so "docker.com" style affinity works for
# hosts like docs.docker.com vs www.docker.com without pulling in a PSL
# dependency. Deliberately small: this only decides a soft ranking signal.
_MULTI_LABEL_SUFFIXES = (
    "co.uk",
    "com.cn",
    "com.au",
    "co.jp",
    "com.br",
    "co.in",
    "org.uk",
    "net.cn",
    "gov.uk",
    "edu.cn",
)

_TARGETING_STRATEGIES = (
    "authoritative_deep_page",
    "same_official_domain_deep_page",
    "generic_deep_page",
    "root_or_landing_page",
)

_ELIGIBLE_RELATIONS = frozenset({"lead", "qualifies"})


@dataclass(frozen=True)
class GapHint:
    """One page's missing-fact statement, turned into a positive target."""

    source_url: str
    source_authority_class: str
    relation: str
    locator: str
    anchors: tuple[str, ...]
    caveat: str
    missing_fact_terms: tuple[str, ...]
    targeting_strategy: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "source_authority_class": self.source_authority_class,
            "relation": self.relation,
            "locator": self.locator[:200],
            "anchors": list(self.anchors[:4]),
            "caveat": self.caveat[:240],
            "missing_fact_terms": list(self.missing_fact_terms),
            "targeting_strategy": self.targeting_strategy,
        }


def authority_class(url: str) -> str:
    """Classify a host as mirror / tutorial / community / unknown.

    A host list can only ever *penalise* known non-authoritative hosts; it must
    never guess that an arbitrary domain is official. Official authority comes
    from the server-owned source role instead (see ``gap_from_extraction``),
    which is why an unknown host is not a claim about trust.
    """

    host = (urlsplit(str(url or "")).netloc or "").casefold()
    if not host:
        return AUTHORITY_UNKNOWN
    host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    for candidate in _TUTORIAL_HOSTS:
        if host == candidate or host.endswith("." + candidate):
            return AUTHORITY_TUTORIAL
    for candidate in _MIRROR_HOSTS:
        if host == candidate or host.endswith("." + candidate):
            return AUTHORITY_MIRROR
    # Bare "www" hosts are not enough to claim community; only explicit
    # community/mirror hosts are penalised, everything else is unknown.
    if host.startswith("blog.") or host.startswith("forum.") or host.startswith("community."):
        return AUTHORITY_COMMUNITY
    return AUTHORITY_UNKNOWN


def path_depth(url: str) -> int:
    path = (urlsplit(str(url or "")).path or "").strip()
    return 0 if path in {"", "/"} else path.count("/") - path.count("//")


def registrable_domain(host: str) -> str:
    """Best-effort registrable domain (``docs.docker.com`` -> ``docker.com``)."""

    value = str(host or "").casefold().split(":", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    labels = [label for label in value.split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    tail = ".".join(labels[-2:])
    if tail in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return tail


def is_root_or_landing(url: str) -> bool:
    path = (urlsplit(str(url or "")).path or "").strip()
    return path in {"", "/"} or path.count("/") <= 1


def target_path_hit(url: str) -> bool:
    lowered = (urlsplit(str(url or "")).path or "").casefold()
    return any(token in lowered for token in _TARGET_PATH_TOKENS)


def is_query_stopword(term: str) -> bool:
    """Whether a term must never appear in a discovery query (negations/fillers).

    Shared with §36B's query-variant builder so both paths strip the same words
    from a single source of truth.
    """

    return str(term).strip().casefold() in _NEGATION_TOKENS


def missing_fact_terms(caveat: str) -> tuple[str, ...]:
    """Extract the positive object of an absence clause (never the negation).

    When the caveat states no absence clause (for example it only says the page
    is the wrong kind of source), an empty tuple is returned on purpose: the
    caller must not turn the raw caveat sentence into query terms.
    """

    lowered = str(caveat or "").casefold()
    matched = False
    for pattern in _ABSENCE_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            lowered = lowered[match.end() :]
            matched = True
            break
    if not matched:
        return ()
    tokens = re.findall(r"[a-z0-9][a-z0-9\-\.\+]{1,}", lowered)
    terms: list[str] = []
    for token in tokens:
        clean = token.strip("-.")
        if len(clean) < 3 or clean in _NEGATION_TOKENS:
            continue
        if clean not in terms:
            terms.append(clean)
        if len(terms) >= _MAX_QUERY_TERMS:
            break
    return tuple(terms)


def targeting_strategy(url: str, *, source_url: str, source_authority_class: str) -> str:
    """Name the page-selection strategy a discovery URL belongs to (diagnostic)."""

    host = (urlsplit(str(url or "")).netloc or "").casefold()
    if is_root_or_landing(url):
        return "root_or_landing_page"
    if source_authority_class == AUTHORITY_OFFICIAL:
        source_host = (urlsplit(str(source_url or "")).netloc or "").casefold()
        if source_host and registrable_domain(host) == registrable_domain(source_host):
            return "same_official_domain_deep_page"
    if target_path_hit(url):
        return "authoritative_deep_page"
    return "generic_deep_page"


def discovery_score(
    url: str,
    *,
    source_url: str,
    source_authority_class: str,
) -> int:
    """Soft ranking score for a discovery URL (never an eligibility decision)."""

    score = 0
    authority = authority_class(url)
    if authority == AUTHORITY_OFFICIAL:
        score += 3
    elif authority in {AUTHORITY_TUTORIAL, AUTHORITY_COMMUNITY}:
        score -= 2
    elif authority == AUTHORITY_MIRROR:
        score -= 1
    if target_path_hit(url):
        score += 2
    score += min(path_depth(url), 3)
    if is_root_or_landing(url):
        score -= 3
    if source_authority_class == AUTHORITY_OFFICIAL:
        source_host = (urlsplit(str(source_url or "")).netloc or "").casefold()
        host = (urlsplit(str(url or "")).netloc or "").casefold()
        # Affinity is registrable-domain based, so an official source keeps its
        # own docs/support subdomains strong while a tutorial source (never
        # "official") cannot lock discovery into itself.
        if source_host and registrable_domain(host) == registrable_domain(source_host):
            score += 3
    return score


_STRATEGY_TIER = {
    "authoritative_deep_page": 0,
    "same_official_domain_deep_page": 1,
    "generic_deep_page": 2,
    "root_or_landing_page": 3,
}


def rank_targeting_candidates(
    urls: Iterable[str],
    *,
    source_url: str,
    source_authority_class: str,
) -> tuple[str, ...]:
    """Deterministic ordering: authoritative deep page > ... > root/landing.

    Strategy tier dominates (the §36A priority order), soft score breaks ties
    inside a tier, and the URL itself is the final tie-break so identical input
    always yields identical output.
    """

    unique: list[str] = []
    for url in urls:
        if url and url not in unique:
            unique.append(url)
    ranked = sorted(
        unique,
        key=lambda url: (
            _STRATEGY_TIER.get(
                targeting_strategy(
                    url,
                    source_url=source_url,
                    source_authority_class=source_authority_class,
                ),
                len(_STRATEGY_TIER),
            ),
            -discovery_score(
                url,
                source_url=source_url,
                source_authority_class=source_authority_class,
            ),
            url,
        ),
    )
    return tuple(ranked)


def gap_from_extraction(
    *,
    relation: str,
    locator: str,
    anchored_spans: Sequence[str],
    caveats: Sequence[str],
    source_url: str,
    source_role: str = "",
) -> GapHint | None:
    """Build a gap hint for a lead/qualifies row, or ``None`` when it must not trigger.

    ``supports`` and ``background`` never trigger; a row without any usable
    locator/anchor or without a caveat never triggers either (nothing to target).
    """

    normalized = str(relation or "").strip().casefold()
    if normalized not in _ELIGIBLE_RELATIONS:
        return None
    anchors = tuple(str(item).strip() for item in anchored_spans if str(item).strip())
    clean_locator = str(locator or "").strip()
    usable_locator = clean_locator if len(clean_locator) >= _MIN_LOCATOR_CHARS else ""
    if not anchors and not usable_locator:
        return None
    caveat = next((str(item).strip() for item in caveats if str(item).strip()), "")
    if not caveat:
        return None
    # Terms may legitimately be empty (a source-quality caveat names no missing
    # fact); the caller then builds the query from claim terms + page intent
    # instead of the raw caveat sentence.
    terms = missing_fact_terms(caveat)
    authority = (
        AUTHORITY_OFFICIAL
        if str(source_role or "").strip().casefold() == "primary"
        else authority_class(source_url)
    )
    strategy = targeting_strategy(
        source_url,
        source_url=source_url,
        source_authority_class=authority,
    )
    return GapHint(
        source_url=str(source_url or ""),
        source_authority_class=authority,
        relation=normalized,
        locator=usable_locator,
        anchors=anchors,
        caveat=caveat,
        missing_fact_terms=terms,
        targeting_strategy=strategy,
    )


def targeted_query_terms(
    gap: GapHint,
    claim_terms: Sequence[str],
    *,
    limit: int = _MAX_QUERY_TERMS,
) -> tuple[str, ...]:
    """Positive bounded query terms: claim subject first, then the missing fact.

    The claim subject is capped at ``_MAX_CLAIM_TERMS`` so the gap's own terms
    (the whole point of §36A) are never crowded out of the query.
    """

    terms: list[str] = []
    for term in claim_terms:
        if len(terms) >= _MAX_CLAIM_TERMS:
            break
        clean = str(term).strip().casefold()
        if len(clean) >= 3 and clean not in terms:
            terms.append(clean)
    for term in gap.missing_fact_terms:
        if term not in terms:
            terms.append(term)
    return tuple(terms[:limit])
