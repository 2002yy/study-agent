"""Which planned question, or which kind of source, is still missing?

Scope: the *next retrieval step* only. This module is advisory and lexical. It
never decides publication, never changes the evidence contract, and never calls
a model. Its output is used for two bounded actions inside
:func:`src.web.research_recovery.recover_public_research`:

* point a search slot that would repeat an already-answered planned question at
  the part of the question no read has addressed yet, or at the missing *kind*
  of source (official documentation, a community thread) instead of appending
  the old fixed "official documentation" padding;
* stop spending searches and reads once every planned question has a body that
  visibly mentions it (the answer still has to be written from those bodies).
  This one is opt-in (``WEB_RESEARCH_COVERAGE_STOP``) because it is the only
  action here that can make a run read less.

Why lexical and not semantic: the semantic question mapping already exists, but
it is one batched model call that runs after retrieval, so it cannot steer
retrieval without paying for extra model calls. The cheap signal available
mid-run is term presence. It is deliberately reported as
``lexical_facet_coverage_next_step_only`` so no reader mistakes it for
adequacy, support, or truth.

The distinction this module keeps visible:

    "five related pages were found" is not
    "each part of the question was addressed by a page we actually read".
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal, Sequence

from src.web.site_pool import SITES, select_sites

COVERAGE_KIND = "lexical_facet_coverage_next_step_only"

#: Source categories that carry first-hand user experience rather than the
#: vendor's own description. The site pool owns the catalogue and its routing.
COMMUNITY_CATEGORIES = frozenset({"zh_community", "en_community"})
# Verified, domain-specific first-hand discussions live in the site's "domain"
# category, not in the generic community categories. Video-only Bilibili is
# deliberately excluded: its search hit is not yet a normal readable body.
DOMAIN_COMMUNITY_KEYS = frozenset({"miyoushe", "nowcoder", "chiphell"})

GapReason = Literal[
    "uncovered_facet",
    "missing_official_source",
    "missing_community_source",
]

#: Words that appear in a question but do not identify a facet. They are
#: two-character Chinese words, so the bigram tokenizer keeps them and they must
#: be removed explicitly.
_QUESTION_WORDS = frozenset(
    {
        "什么", "怎么", "如何", "是否", "哪些", "哪个", "为什", "可以", "需要",
        "影响", "情况", "问题", "方面", "相关", "以及", "还是", "这个", "那个",
        "我们", "他们", "一个", "没有", "如果", "因为", "所以", "还是", "有什",
        "么限", "限制", "要求", "规定", "介绍", "说明", "区别", "对比", "比较",
        "推荐", "体验", "评价", "值得", "选择", "使用", "主要", "具体",
    }
)

#: A question that names official material keeps its scoped documentation
#: search. Without one of these, the fixed "official documentation" padding
#: query is noise and its slot is better spent on a missing facet.
_OFFICIAL_CUES = (
    "官方", "文档", "规范", "发布说明", "版本说明", "接口文档",
    "documentation", "official", "docs", "release notes", "changelog",
    "specification", "api reference",
)

_ASCII = re.compile(r"[a-z0-9][a-z0-9_.+-]*")
_CJK = re.compile(r"[\u4e00-\u9fff]")

#: A site's search page is not always the host its real content lives on.
_SCOPE_HOST = {"hn.algolia.com": "news.ycombinator.com"}

#: Characters that make a two-character CJK bigram a grammatical fragment
#: rather than a content word (e.g. "与检" from "长事务与检查点").
_CJK_FUNCTION_CHARS = frozenset(
    "的与和或在是有么怎要可做否为何如哪那些个这们还就都也及把被让给对从向并而但若因所以到会能将已未不没上下里中"
)


def _is_cjk(term: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]+", term))


def _terms(text: str) -> tuple[str, ...]:
    """Content terms of one question: ASCII words and CJK phrases.

    CJK is split at function characters rather than into bigrams: bigrams like
    "与检" or "份与" never appear in a page, while "文件"+"系统" appearing
    separately lets a generic tutorial look like a mention of network
    filesystems. A phrase such as "网络文件系统" is one term.
    """

    lowered = str(text or "").casefold()
    tokens: list[str] = list(
        re.findall(r"[a-z0-9]+(?:[_.+-][a-z0-9]+)*", lowered)
    )
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        current: list[str] = []
        for char in run:
            if char in _CJK_FUNCTION_CHARS:
                tokens.append("".join(current))
                current = []
                continue
            current.append(char)
        tokens.append("".join(current))
    seen: set[str] = set()
    kept: list[str] = []
    for token in tokens:
        if len(token) < 2 or token in _QUESTION_WORDS or token in seen:
            continue
        seen.add(token)
        kept.append(token)
    return tuple(kept)


def _host(value: str) -> str:
    """Host of a URL or of a bare host name (``sqlite.org``)."""

    from urllib.parse import urlsplit

    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    parts = urlsplit(raw if "://" in raw else "//" + raw)
    host = (parts.hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _host_matches(host: str, expected: str) -> bool:
    if not host or not expected:
        return False
    return host == expected or host.endswith("." + expected)


_ASCII_CONTAINS: dict[str, re.Pattern[str]] = {}

#: Facet terms must occur together within this many characters to count as one
#: statement. A long page mentions "backup" in a changelog and "restore" in a
#: table of contents; only proximity makes it a page about backup and restore.
_FACET_WINDOW = 240
_MAX_HITS_PER_TERM = 60


def _contains(text: str, term: str) -> bool:
    """Whole-word ASCII match with a light plural/participle suffix.

    "concurrent writes" must cover a term written as "concurrent write"; a bare
    substring test would also let "api" match inside "FastAPI".
    """

    if _is_cjk(term):
        return term in text
    return bool(_pattern(term).search(text))


def _pattern(term: str) -> re.Pattern[str]:
    pattern = _ASCII_CONTAINS.get(term)
    if pattern is None:
        pattern = re.compile(
            rf"(?<![a-z0-9]){re.escape(term)}(?:s|es|ed|ing)?(?![a-z0-9])"
        )
        _ASCII_CONTAINS[term] = pattern
    return pattern


def _term_positions(text: str, term: str) -> list[int]:
    if _is_cjk(term):
        positions: list[int] = []
        start = 0
        while len(positions) < _MAX_HITS_PER_TERM:
            index = text.find(term, start)
            if index < 0:
                break
            positions.append(index)
            start = index + len(term)
        return positions
    return [
        match.start()
        for index, match in enumerate(_pattern(term).finditer(text))
        if index < _MAX_HITS_PER_TERM
    ]


def _covered_terms(text: str, terms: Sequence[str], needed: int) -> tuple[str, ...]:
    """Distinct terms that occur together in one window of the body."""

    hits: list[tuple[int, str]] = []
    for term in terms:
        for position in _term_positions(text, term):
            hits.append((position, term))
    if not hits:
        return ()
    hits.sort()
    best: tuple[str, ...] = ()
    start = 0
    for end, (position, _) in enumerate(hits):
        while position - hits[start][0] > _FACET_WINDOW:
            start += 1
        window = tuple(dict.fromkeys(term for _, term in hits[start : end + 1]))
        if len(window) > len(best):
            best = window
        if len(best) >= needed:
            return best
    return best


@dataclass(frozen=True)
class Facet:
    """One part of the question, with its own planned search query."""

    id: str
    question: str
    query: str
    terms: tuple[str, ...]
    distinctive: tuple[str, ...]


@dataclass(frozen=True)
class FacetStatus:
    facet_id: str
    question: str
    assessable: bool
    covered: bool
    matched_terms: tuple[str, ...] = ()
    body_urls: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "facet_id": self.facet_id,
            "question": self.question,
            "assessable": self.assessable,
            "covered": self.covered,
            "matched_terms": list(self.matched_terms),
            "body_urls": list(self.body_urls),
        }


@dataclass(frozen=True)
class SourceNeed:
    """What *kind* of source the question asks for, and why."""

    official: bool
    reason: str
    community_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class GapStep:
    reason: GapReason
    query: str
    facet_id: str = ""
    host: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "reason": self.reason,
            "query": self.query,
            "facet_id": self.facet_id,
            "host": self.host,
        }


@dataclass(frozen=True)
class CoverageReport:
    facets: tuple[FacetStatus, ...]
    source: SourceNeed
    read_hosts: tuple[str, ...]
    missing_official: bool
    missing_community_hosts: tuple[str, ...]
    reason: str = ""

    @property
    def uncovered(self) -> tuple[FacetStatus, ...]:
        return tuple(item for item in self.facets if item.assessable and not item.covered)

    @property
    def source_gap(self) -> bool:
        return self.missing_official or bool(self.missing_community_hosts)

    @property
    def complete(self) -> bool:
        """Every facet is assessable and covered, and no source kind is missing.

        An unassessable facet (no vocabulary shared with the bodies we could
        read) is never treated as covered, and a run with no facets at all is
        never complete. This output only swaps or stops a bounded search; the
        writer's evidence rules are untouched.
        """

        return (
            bool(self.facets)
            and all(item.assessable and item.covered for item in self.facets)
            and not self.source_gap
        )

    def status_for(self, facet_id: str) -> FacetStatus | None:
        return next((item for item in self.facets if item.facet_id == facet_id), None)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": COVERAGE_KIND,
            "facets": [item.to_dict() for item in self.facets],
            "uncovered_facets": [item.facet_id for item in self.uncovered],
            "source": {
                "official_expected": self.source.official,
                "reason": self.source.reason,
                "community_hosts": list(self.source.community_hosts),
            },
            "read_hosts": list(self.read_hosts),
            "missing_official_source": self.missing_official,
            "missing_community_hosts": list(self.missing_community_hosts),
            "complete": self.complete,
            "reason": self.reason,
        }


def plan_facets(
    query_plan: Sequence[dict[str, str]] | None,
    question: str,
    *,
    questions: dict[str, str] | None = None,
) -> tuple[Facet, ...]:
    """Build the facet list from the plan's research-question ids.

    ``questions`` maps an rq id to the question text the interpreter wrote; the
    plan row's ``query`` is the search-shaped phrase for it. Terms come from the
    question text (it names the facet), the query is what a gap step searches.
    A plan-less run has exactly one facet: the question itself, which is never
    used for an early stop.
    """

    rows: list[Facet] = []
    seen: set[str] = set()
    question_map = dict(questions or {})
    for index, row in enumerate(query_plan or []):
        if not isinstance(row, dict):
            continue
        query = str(row.get("query") or "").strip()
        rq_id = str(row.get("rq_id") or "").strip() or f"facet-{index + 1}"
        if not query or rq_id in seen:
            continue
        seen.add(rq_id)
        text = str(question_map.get(rq_id) or "").strip() or query
        # The question names the facet; the planned query is what a search
        # engine will be given, so both vocabularies can appear in a body.
        rows.append(Facet(id=rq_id, question=text, query=query,
                          terms=_merge_terms(_terms(text), _terms(query)),
                          distinctive=()))
    if not rows:
        text = " ".join(str(question or "").split())
        return (Facet(id="facet-question", question=text, query=text,
                      terms=_terms(text), distinctive=()),)
    # A term that appears in every facet cannot tell them apart: "SQLite" and
    # "WAL" are the subject, "backup" is the missing facet.
    shared: set[str] = set()
    for facet in rows:
        others = [other for other in rows if other.id != facet.id]
        own = set(facet.terms)
        for other in others:
            shared |= own & set(other.terms)
    return tuple(
        Facet(id=facet.id, question=facet.question, query=facet.query,
              terms=facet.terms,
              distinctive=tuple(term for term in facet.terms if term not in shared))
        for facet in rows
    )


def _merge_terms(*groups: Iterable[str]) -> tuple[str, ...]:
    merged: list[str] = []
    for group in groups:
        for term in group:
            if term not in merged:
                merged.append(term)
    return tuple(merged)


def community_hosts_for(question: str, *, limit: int = 2) -> tuple[str, ...]:
    """Community sites the existing site pool would route this question to.

    The pool already decides this from the question's domain and intent words;
    this function only filters its answer to first-hand-experience sites. It
    does not add sites and does not execute a search.
    """

    # The normal browser route stops at three sites, often Google/Reddit/HN.
    # Inspect the *already verified* wider route to discover the V2EX/LINUX DO
    # community options without browsing every site or enabling unverified ones.
    routed = [
        site for site in select_sites(question, limit=len(SITES))
        if site.category in COMMUNITY_CATEGORIES or site.key in DOMAIN_COMMUNITY_KEYS
    ]
    local_category = "zh_community" if _CJK.search(question) else "en_community"
    preferred = [site for site in routed if site.key in DOMAIN_COMMUNITY_KEYS]
    preferred.extend(site for site in routed if site.category == local_category)
    preferred.extend(site for site in routed if site not in preferred)
    hosts: list[str] = []
    for site in preferred:
        host = _host(site.home)
        host = _SCOPE_HOST.get(host, host)
        if host and host not in hosts:
            hosts.append(host)
        if len(hosts) >= limit:
            break
    return tuple(hosts)


def source_need(
    question: str,
    *,
    official_hosts: Iterable[str] = (),
    community_hosts: Iterable[str] = (),
) -> SourceNeed:
    """Classify the question's source need without a model call."""

    hosts = tuple(dict.fromkeys(host for host in official_hosts if host))
    text = str(question or "").casefold()
    cue = next((marker for marker in _OFFICIAL_CUES if marker in text), "")
    official = bool(hosts) or bool(cue)
    if hosts:
        reason = "official_hosts_named_by_the_question"
    elif cue:
        reason = f"official_material_named:{cue}"
    elif community_hosts:
        reason = "experience_question_routed_to_community_sites"
    else:
        reason = "no_official_or_community_kind_requested"
    return SourceNeed(official=official, reason=reason,
                      community_hosts=tuple(dict.fromkeys(community_hosts)))


def assess_coverage(
    facets: Sequence[Facet],
    bodies: Sequence[tuple[str, str]],
    *,
    question: str = "",
    official_hosts: Iterable[str] = (),
    community_hosts: Iterable[str] = (),
) -> CoverageReport:
    """Match read bodies against facets and source kinds (lexical, advisory)."""

    hosts = tuple(dict.fromkeys(_host(host) for host in official_hosts if host))
    community = tuple(dict.fromkeys(host for host in community_hosts if host))
    asked = " ".join(str(question or "").split()) or " ".join(
        facet.question for facet in facets
    )
    need = source_need(asked, official_hosts=hosts, community_hosts=community)
    read_hosts: list[str] = []
    lowered: list[tuple[str, str]] = []
    for url, text in bodies:
        host = _host(url)
        if host and host not in read_hosts:
            read_hosts.append(host)
        lowered.append((str(url or ""), str(text or "").casefold()))
    # A Chinese facet cannot be checked against an English-only body: absence
    # there is not evidence of a gap, so the facet stays unassessable and the
    # engine keeps its existing behaviour instead of chasing a phantom.
    corpus_has_cjk = any(_CJK.search(text) for _, text in lowered)
    statuses: list[FacetStatus] = []
    for facet in facets:
        terms = (
            facet.distinctive
            if corpus_has_cjk
            else tuple(term for term in facet.distinctive if not _is_cjk(term))
        )
        if not terms:
            statuses.append(FacetStatus(facet_id=facet.id, question=facet.question,
                                        assessable=False, covered=False))
            continue
        matched: list[str] = []
        urls: list[str] = []
        needed = min(2, len(terms))
        for url, text in lowered:
            window = _covered_terms(text, terms, needed)
            if len(window) < needed:
                continue
            for term in window:
                if term not in matched:
                    matched.append(term)
            if url not in urls:
                urls.append(url)
        statuses.append(
            FacetStatus(
                facet_id=facet.id,
                question=facet.question,
                assessable=True,
                covered=len(matched) >= needed,
                matched_terms=tuple(matched),
                body_urls=tuple(urls),
            )
        )
    missing_official = need.official and not any(
        _host_matches(host, expected) for host in read_hosts for expected in hosts
    )
    # One first-hand thread satisfies the expectation: asking every routed
    # community for every question would spend the budget for no new question.
    community_read = any(
        _host_matches(host, expected)
        for host in read_hosts
        for expected in need.community_hosts
    )
    missing_community = () if community_read else need.community_hosts
    reasons = []
    if need.official and not missing_official:
        reasons.append("official_source_read")
    if missing_official:
        reasons.append("official_source_not_read")
    if missing_community:
        reasons.append("community_source_not_read")
    return CoverageReport(
        facets=tuple(statuses),
        source=need,
        read_hosts=tuple(read_hosts),
        missing_official=missing_official,
        missing_community_hosts=missing_community,
        reason=",".join(reasons) or "no_source_expectation",
    )


def _ascii_query(text: str) -> str:
    return " ".join(_ASCII.findall(str(text or "").casefold()))


def _gap_query(
    facet: Facet | None, question: str, host: str = "", *, require_ascii: bool = False
) -> str:
    """Search phrase for a gap, scoped to a host when one is given.

    Official documentation hosts are scoped only with ASCII keywords: a Chinese
    sentence sent to ``site:sqlite.org`` returns dictionary pages, a lesson
    recorded in the official-index slice. Community sites are the reverse - a
    Chinese question scoped to a Chinese site is exactly the intended query.
    """

    candidates: list[str] = []
    # A generated English facet is valuable for international search, but a
    # site-native Chinese search should use the user's Chinese vocabulary.
    if host and _CJK.search(question) and host in {
        "v2ex.com", "linux.do", "juejin.cn", "miyoushe.com", "nowcoder.com", "chiphell.com"
    }:
        if facet is not None and _CJK.search(facet.question):
            native_phrase = facet.question
            if host == "miyoushe.com":
                # The site chooses a separate search page per game. A narrow
                # facet can omit that game even when the user specified it.
                miyoushe = next((site for site in SITES if site.key == "miyoushe"), None)
                if miyoushe is not None:
                    for keywords, _template in miyoushe.search_variants:
                        if (any(word in question for word in keywords)
                                and not any(word in native_phrase for word in keywords)):
                            native_phrase = f"{keywords[0]} {native_phrase}"
            candidates.append(native_phrase)
        candidates.append(" ".join(str(question or "").split()))
    if facet is not None:
        candidates.extend([_ascii_query(facet.query), _ascii_query(facet.question)])
        candidates.extend([facet.query, facet.question])
    candidates.append(" ".join(str(question or "").split()))
    if require_ascii:
        phrase = next(
            (item.strip() for item in candidates if _ascii_query(item)), ""
        )
    else:
        phrase = next((item.strip() for item in candidates if item.strip()), "")
    if not phrase:
        return ""
    if host:
        if require_ascii and not _ascii_query(phrase):
            return ""
        return f"{phrase} site:{host}"
    return phrase


def next_gap_step(
    report: CoverageReport,
    *,
    facets: Sequence[Facet],
    question: str,
    official_hosts: Iterable[str] = (),
    searched: Iterable[str] = (),
    skip_facet_ids: Iterable[str] = (),
) -> GapStep | None:
    """The single most valuable next search, or ``None`` when there is no gap.

    Order: a missing community thread first (an experience question is not
    answered by the vendor's own page), then missing official documentation,
    then the first uncovered planned question. A query already searched is
    never repeated.
    """

    done = {" ".join(str(item or "").split()).casefold() for item in searched}
    skip = set(skip_facet_ids)
    by_id = {facet.id: facet for facet in facets}
    uncovered = [item for item in report.uncovered if item.facet_id not in skip]
    facet = by_id.get(uncovered[0].facet_id) if uncovered else None

    def usable(query: str) -> bool:
        return bool(query) and query.casefold() not in done

    if report.missing_community_hosts:
        host = _SCOPE_HOST.get(report.missing_community_hosts[0],
                               report.missing_community_hosts[0])
        query = _gap_query(facet, question, host)
        if usable(query):
            return GapStep(reason="missing_community_source", query=query,
                           facet_id=facet.id if facet else "", host=host)
    if report.missing_official:
        host = next((item for item in official_hosts if item), "")
        query = _gap_query(facet, question, host, require_ascii=True)
        if usable(query):
            return GapStep(reason="missing_official_source", query=query,
                           facet_id=facet.id if facet else "", host=host)
    if facet is not None:
        for phrase in (_gap_query(facet, question), facet.query, facet.question):
            phrase = " ".join(str(phrase or "").split())
            if usable(phrase):
                return GapStep(reason="uncovered_facet", query=phrase, facet_id=facet.id)
    return None
