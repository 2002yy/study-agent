"""B-Search-2B9-G: bounded, question-ranked in-page link discovery.

One fetch feeds this module; it never fetches a child page itself, so every real
HTTP request still belongs to the caller and still spends the caller's read
quota. What it adds over a plain "first five <a href>" scan:

* a real HTML parser (lxml) instead of a regex over raw text;
* anchor text, URL path and the nearest preceding heading are captured together;
* template noise (language switches, login, footer/ad/boilerplate, navigation
  links repeated across the page) is detected generically - no site allowlists,
  no hardcoded URLs;
* every candidate is classified as ``article`` / ``category`` / ``home`` /
  ``uncertain`` and ranked by relevance to the question, so a directory page is
  never mistaken for a正文, and language switchers cannot fill the slots.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from lxml import html as lxml_html  # type: ignore[import-untyped]

from src.web.recovery_candidates import canonical_document

# Hard bounds: one page can never make the agent process an unbounded document.
MAX_LINKS = 500
MAX_HTML_BYTES = 300_000

_SKIP_PREFIXES = ("#", "javascript:", "mailto:", "tel:", "data:", "about:")

# Generic patterns - not site specific.
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2,4})?$")
_LOGIN_RE = re.compile(
    r"^(?:log[\s_-]?in|log[\s_-]?out|sign[\s_-]?in|sign[\s_-]?up|register|"
    r"account|profile|登录|登入|注册|退出|账户)\b",
    re.I,
)
_BOILERPLATE_RE = re.compile(
    r"(?:privacy|terms|cookie|disclaimer|copyright|contact|sitemap|"
    r"advertis|sponsor|donate|newsletter|隐私|条款|关于我们|联系我们|广告|捐赠|版权)",
    re.I,
)
_CATEGORY_WORD_RE = re.compile(
    r"\b(?:category|categories|cat|list|index|all|browse|archive|tag|tags|"
    r"portal|overview|directory|contents|toc|glossary|"
    r"分类|目录|列表|索引|导航)\b",
    re.I,
)
# Common self-names for language switchers (a language feature, not a site list).
_LANGUAGE_NAME_RE = re.compile(
    r"^(?:english|deutsch|fran[çc]ais|espa[ñn]ol|italiano|portugu[êe]s|русский|"
    r"日本語|中文|中國|한국어|polski|nederlands|türkçe|čeština|magyar|svenska|"
    r"dansk|suomi|norsk|română|العربية|فارسی|हिन्दी|ไทย|tiếng\s*việt|bahasa)$",
    re.I,
)


@dataclass
class Candidate:
    """One same-origin link found on the fetched page."""

    url: str
    anchor: str = ""
    path: str = ""
    context: str = ""
    page_type: str = "uncertain"
    score: float = 0.0
    why: str = ""
    repeated: int = 0
    order: int = 0
    matched: frozenset[str] = frozenset()

    def as_dict(self) -> dict[str, str]:
        return {
            "url": self.url,
            "anchor": self.anchor,
            "path": self.path,
            "context": self.context,
            "type": self.page_type,
            "score": str(round(self.score, 2)),
            "why": self.why,
        }


def question_terms(question: str) -> set[str]:
    """Deterministic question tokens: ASCII words plus CJK runs and their bigrams."""
    lowered = (question or "").lower()
    terms = {word for word in re.findall(r"[a-z0-9]{3,}", lowered)}
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) >= 2:
            terms.add(run)
        terms.update(run[i:i + 2] for i in range(len(run) - 1))
    return terms


#: Clause boundaries a research question uses to state more than one goal. Purely
#: structural: the split names what the question already asks, and injects no answer.
#: The English connectors need word boundaries, otherwise "st-and-ard" or "s-or-ting"
#: would be cut apart.
_CLAUSE_SPLIT = re.compile(
    r"[，,；;。？?！!、\n]+|(?:并且|而且|以及|同时|另外)|\band\b|\bor\b")
_CLAUSE_CONNECT = re.compile(r"(?:和|与|及|跟)")


#: Mechanism/relation markers. SUPPORTED needs one, so a page that merely shares keywords
#: with a goal can never settle it (keyword containment is not semantic support).
_RELATION_MARKERS = (
    "因为", "由于", "导致", "造成", "使得", "通过", "意味着", "从而", "以便", "为了",
    "作用是", "用于", "取决于", "所以", "因此",
    "because", "due to", "causes", "means", "so that", "requires", "leads to", "by ",
)

#: Explicit contradiction near the goal terms: the body argues against the claim.
_CONFLICT_MARKERS = ("并非", "不是", "错误", "不正确", "incorrect", "myth", "not true")


def classify_goal_candidate(terms: tuple[str, ...] | list[str], content: str, *,
                            min_ratio: float = 0.6, min_chars: int = 120,
                            window: int = 240) -> tuple[str, dict]:
    """CANDIDATE-level signal for one goal against one body: missing | explored only.

    It can NEVER grant semantic support - that requires the independent claim verifier
    (`research_claim_verifier`). The window rule only says "this body is worth checking",
    so no caller can inherit evidence authority from a keyword pattern.
    """
    text = content or ""
    lowered = text.lower()
    hits = [term for term in terms if term and term.lower() in lowered]
    if not hits:
        return "missing", {"terms_hit": [], "relation": "", "excerpt": "",
                           "ratio": 0.0, "conflict": ""}
    base_ratio = round(len(hits) / len(terms), 2) if terms else 0.0
    for term in hits:
        position = lowered.find(term.lower())
        while position >= 0:
            start, end = max(0, position - window), position + window
            chunk = lowered[start:end]
            in_window = [item for item in terms if item.lower() in chunk]
            ratio = len(in_window) / len(terms) if terms else 0.0
            if len(text) >= min_chars and ratio >= min_ratio:
                marker = next((item for item in _RELATION_MARKERS if item in chunk), "")
                if marker:
                    conflict = next((item for item in _CONFLICT_MARKERS if item in chunk), "")
                    # A candidate signal, never a verdict: support must come from the
                    # independent claim verifier.
                    return "explored", {
                        "terms_hit": in_window, "relation": marker, "conflict": conflict,
                        "ratio": round(ratio, 2),
                        "excerpt": text[start:end].replace("\n", " ")}
            position = lowered.find(term.lower(), position + 1)
    return "explored", {"terms_hit": hits, "relation": "", "excerpt": "",
                        "ratio": base_ratio, "conflict": ""}


def derive_sub_goals(question: str, *, limit: int = 3) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Split a question into its own sub-goals when the caller supplies none.

    Deterministic and answer-free: each clause becomes a goal whose terms are the clause's
    own tokens. A single-clause question returns nothing (the question IS the goal), so the
    default entry can drive per-goal progress without hardcoded knowledge.
    """
    text = (question or "").strip()
    if not text:
        return ()
    raw_clauses = [part.strip(" \t:：") for part in _CLAUSE_SPLIT.split(text)]
    clauses = [part for part in raw_clauses if len(part) >= 4]
    # A coordinated pair inside one clause ("A 与 B 的区别") is one goal, not two, unless the
    # clause already carries its own question word.
    if len(clauses) == 1 and "?" in text or len(clauses) == 1 and "？" in text:
        parts = [part.strip() for part in _CLAUSE_CONNECT.split(clauses[0]) if len(part) >= 4]
        if len(parts) > 1:
            clauses = parts
    goals: list[tuple[str, tuple[str, ...]]] = []
    seen: list[set[str]] = []
    for clause in clauses:
        terms = question_terms(clause)
        if not terms:
            continue
        # Drop a clause whose tokens add nothing over an earlier goal.
        if any(terms <= earlier for earlier in seen):
            continue
        seen.append(terms)
        goals.append((clause[:32], tuple(sorted(terms))))
        if len(goals) >= limit:
            break
    if len(goals) < 2:
        return ()
    return tuple(goals)


# --- navigation-family display diversity ---------------------------------------------

_VERSION_SEGMENT = re.compile(
    r"^(?:\d+(?:\.\d+)*|current|devel|beta|rc\d*|stable|latest|master)$"
)
#: Only a path that explicitly marks documentation puts a version segment here. This is
#: what keeps /posts/2024/guide or /books/1/chapter from being folded as "versions".
_DOC_CONTEXT = frozenset({
    "docs", "doc", "documentation", "manual", "man", "reference", "handbook", "api",
})
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def version_family(url: str) -> tuple[str, str]:
    """(scheduling-family, version token) for a URL with an EXPLICIT docs version path.

    Locale and tracking normalisation is reused from the existing
    ``recovery_candidates.canonical_document`` (a scheduling identity only; it never
    rewrites a fetched URL). A segment counts as a version only when a documentation
    context token sits immediately before it and the token is not a calendar year, so
    ``/docs/17/mvcc.html`` and ``/docs/18/mvcc.html`` become one family while
    ``/posts/2024/guide`` and ``/books/1/chapter`` never do.
    """
    base = canonical_document(url)
    head, _, rest = base.partition("/")
    segments = rest.split("/") if rest else []
    for index, segment in enumerate(segments):
        token = segment.casefold()
        if not _VERSION_SEGMENT.fullmatch(token) or _YEAR_RE.match(token):
            continue
        if index == 0 or segments[index - 1].casefold() not in _DOC_CONTEXT:
            continue
        folded = list(segments)
        folded[index] = "*"
        return f"{head}/{'/'.join(folded)}", token
    return "", ""


def requested_versions(question: str) -> set[str]:
    """Version tokens the question names, using version context only.

    Conservative on purpose: a bare number is not a version. It is one when it is
    dotted (``9.6``), v-prefixed (``v17``), written after a version word, attached to a
    latin product name (``PostgreSQL 17``), or part of an explicit comparison
    (``17 与 18``). Calendar years never count.
    """
    text = (question or "").lower()
    raw = question or ""
    found: set[str] = set()
    found |= set(re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", text))
    found |= set(re.findall(r"\bv(\d+(?:\.\d+)*)\b", text))
    found |= set(re.findall(r"(?:版本|version|docs?)\s*(\d+(?:\.\d+)*)", text))
    # A product-like name (internal capital, e.g. PostgreSQL / Kubernetes) followed by a
    # number is a version reference, regardless of what follows: "PostgreSQL 17
    # performance" still names 17. Ordinary English words are not product names
    # ("Explain 3 reasons" / "Compare 3 methods" / "Describe 3 PostgreSQL concepts"),
    # and a dotted version is caught by the first rule ("Python 3.12 f-string changes").
    found |= set(re.findall(
        r"\b[A-Za-z][A-Za-z0-9_-]*[A-Z][A-Za-z0-9_-]*\s+(\d+(?:\.\d+)*)\b", raw))
    found |= set(re.findall(r"\b(\d+(?:\.\d+)*)\s*(?:与|和|vs\.?|versus)\s*\d", text))
    found |= set(re.findall(r"\d+\s*(?:与|和|vs\.?|versus)\s*(\d+(?:\.\d+)*)", text))
    return {token for token in found if not _YEAR_RE.match(token)}


def diversify_navigation_families(
    ranked: list[Candidate], *, question: str = "", min_family: int = 3
) -> list[Candidate]:
    """Stop one *documentation version* family from filling every display slot.

    Suppression needs a question context: with no question the input is returned
    unchanged, so existing callers cannot change behaviour by accident. Identity is
    preserved — no version is canonicalised, no URL is rewritten, and a suppressed link
    simply does not occupy a shown slot (so it gains no confirmation from this path).
    """
    if not (question or "").strip():
        return ranked
    families: dict[str, list[Candidate]] = {}
    for candidate in ranked:
        family, _token = version_family(candidate.url)
        if family:
            families.setdefault(family, []).append(candidate)

    requested = requested_versions(question)
    drop: set[str] = set()
    for members in families.values():
        if len(members) < min_family:
            continue
        mentioned = [c for c in members if version_family(c.url)[1] in requested]
        if mentioned:
            keep = {c.url for c in mentioned}
        else:
            keep = {max(members, key=lambda c: (c.score, -c.order)).url}
        drop.update(c.url for c in members if c.url not in keep)
    return [c for c in ranked if c.url not in drop]


#: The reader collapses whitespace (``clean_article_text`` runs ``\s+`` -> " "), so line
#: structure is NOT available here. An index/version page is instead recognisable by a
#: SHORT body whose content is mostly tokens: many bare numbers (version switchers) or
#: many list separators. Two signals together, never a single one — mechanism prose
#: mentions a version once, not five times, in under 1,200 characters.
_NAV_MAX_CHARS = 1_200
_NAV_MIN_NUMBERS = 5
_NAV_MIN_SEPARATORS = 2
_NAV_SEPARATORS = ("|", "·", "»", "›", "/")


def looks_like_navigation(text: str) -> bool:
    """True when a SHORT extracted body reads as an index/version page, not prose.

    Both token signals must hold, so a short game guide that merely lists five numbered
    steps (numbers but no separators) is not mistaken for a directory.
    """
    body = (text or "").strip()
    if not body or len(body) > _NAV_MAX_CHARS:
        return False
    numbers = len(re.findall(r"\b\d+(?:\.\d+)*\b", body))
    separators = sum(body.count(char) for char in _NAV_SEPARATORS)
    return numbers >= _NAV_MIN_NUMBERS and separators >= _NAV_MIN_SEPARATORS


#: Below this there is no body at all (empty, blocked, or a JS shell) - not a short page.
#: Eligibility is decided by the prose measure below, never by page length.
MIN_BODY_CHARS = 60
#: A prose block is a run of text with sentence punctuation, not a nav item or a button.
PROSE_BLOCK_MIN_CHARS = 60
#: Two punctuated sentences of this total size is content a claim could be drawn from; a
#: single-paragraph article counts. Sentence density — not line structure — decides, so a
#: link list cannot inflate the measure and a short real answer is not thrown away.
MIN_PROSE_CHARS = 80
MIN_PROSE_CHARS_PER_UNIT = 12
MIN_PROSE_SENTENCES = 2
#: Below this prose share a list-like page is an item/category page, not an answer.
LIST_PROSE_SHARE = 0.35
_SENTENCE_PUNCT = re.compile(r"[.。！？!?;；:：]")
#: Sentence units KEEP their terminator, so a unit is prose only if it ends like a sentence
#: (or is a long unpunctuated line). A column of short link labels is therefore not prose.
_UNIT_SPLIT = re.compile(r"(?<=[.。！？!?;；])\s*|\n+")
_BLOCK_SPLIT = re.compile(r"\n\s*\n|\n")


def prose_blocks(text: str) -> list[str]:
    """Blocks that read as prose: long enough and carrying sentence punctuation.

    A nav item, a button or a link label is short and unpunctuated, so it cannot inflate the
    measure however many of them a page lists.
    """
    blocks = [block.strip() for block in _BLOCK_SPLIT.split(text or "") if block.strip()]
    return [block for block in blocks
            if len(block) >= PROSE_BLOCK_MIN_CHARS and _SENTENCE_PUNCT.search(block)]


def prose_units(text: str) -> list[str]:
    """Sentence-like units: punctuated sentences, or long unpunctuated lines."""
    units: list[str] = []
    for raw in _UNIT_SPLIT.split(text or ""):
        unit = raw.strip()
        if len(unit) < MIN_PROSE_CHARS_PER_UNIT:
            continue
        if _SENTENCE_PUNCT.search(unit) or len(unit) >= PROSE_BLOCK_MIN_CHARS:
            units.append(unit)
    return units


#: Requirement boundaries inside one goal: punctuation and connectors only. Never a word
#: list, and never a model call - a goal asking for two things needs two answers.
_ITEM_SPLIT = re.compile(r"[，,、；;]|以及|并且|同时")


def answer_items(label: str) -> tuple[str, ...]:
    """The necessary requirements inside one goal, taken from its own wording.

    "为什么不阻塞、主要代价是什么" requires two separate answers; "如何避免读写互相阻塞"
    requires one. The split is deterministic (punctuation and connectors), so goal completion
    is decided by which items the evidence covers, not by a keyword overlap ratio.
    """
    text = (label or "").strip()
    if not text:
        return ()
    parts = [part.strip(" 。？！?.、，,") for part in _ITEM_SPLIT.split(text)]
    items = tuple(part for part in parts if len(part) >= 2)
    return items or (text,)


#: Separators that make a question a COMPARISON of two things. Never a topic glossary: it
#: reads the question's own wording.
_COMPARE_SEP = re.compile(r"\s*(?:与|和|及|vs\.?|VS\.?|对比|相比)\s*")
#: Particles that glue an entity to the rest of a phrase ("Minecraft 中漏斗" -> "漏斗").
_PARTICLES = "中上下的里内外与和及对把将"
#: CJK runs let a side be taken from either end: the LEFT side ends with its entity, the
#: RIGHT side begins with it.
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
#: Characters that end the entity phrase on the right side ("投掷器有什么区别" -> "投掷器").
_SIDE_STOP = "在的与和及对把将有多么几哪吗呢有为会是能可怎如何什"


def _entity(chunk: str, *, leading: bool) -> str:
    """The entity phrase a comparison side names, with its connective tail removed."""
    text = (chunk or "").strip("　 ，,。？?！!：:；;")
    if not text:
        return ""
    runs = _CJK_RUN.findall(text)
    if not runs:
        return text.split()[0] if text.split() else text       # "A 和 B"
    run = runs[0] if leading else runs[-1]
    if leading:
        cut = len(run)
        for index, char in enumerate(run):
            if char in _SIDE_STOP:
                cut = index
                break
        run = run[:cut]
    return run.lstrip(_PARTICLES)


def compare_sides(text: str) -> tuple[str, str] | None:
    """The two things a question compares, or None when it compares nothing.

    "Minecraft 中漏斗和投掷器在物品传输上的区别是什么" -> ("漏斗", "投掷器"). This plans
    evidence only: two sources mentioning A and B still say nothing about how they differ, so
    it never grants support on its own.
    """
    # A question may contain more than one "与" ("围棋让子棋的贴目与对局规则与分先棋有何不同？"),
    # and only one of those splits resolves two entities. Try each separator in order and take the
    # first pair that works, so a comparison is not missed because the wording had two of them.
    for found in _COMPARE_SEP.finditer(text or ""):
        left = _entity(text[:found.start()], leading=False)   # the entity ENDS the left chunk
        right = _entity(text[found.end():], leading=True)     # the entity BEGINS the right one
        if left and right and left != right:
            return left, right
    return None


def looks_like_list(text: str) -> bool:
    """True when a passage is a list of names/links rather than prose sentences.

    ``looks_like_navigation`` needs numbers and separators, which an item list such as
    " - 末影珍珠 - 末影之眼 - ..." has none of. A passage with many short separated segments
    and almost no sentence punctuation is a list, whatever it lists.
    """
    body = (text or "").strip()
    if not body:
        return False
    bullets = len(re.findall(r"(?:^|\s)[-•·|»]\s", body))
    sentences = len(re.findall(r"[.。！？!?]", body))
    segments = [segment for segment in re.split(r"\s[-•·|»]\s", body) if segment.strip()]
    short = sum(1 for segment in segments if len(segment.strip()) <= 24)
    return (bullets >= 4 and sentences <= 1) or len(segments) >= 6 and short >= len(segments) - 1


def classify_body(text: str) -> tuple[str, dict[str, Any]]:
    """Classify an extracted body as substantive / navigation / unusable.

    Sentence density and page type decide this, not a length threshold: a 250-character
    answer counts, and a 4,000-character link farm does not. Navigation detection is the
    shared ``looks_like_navigation`` rule and wins outright, because a numbered index list
    is prose-shaped without being prose.
    """
    body = (text or "").strip()
    if len(body) < MIN_BODY_CHARS:
        return "unusable", {"chars": len(body), "prose_chars": 0, "prose_blocks": 0,
                            "prose_share": 0.0, "looks_like_navigation": False,
                            "reason": "no_body"}
    units = prose_units(body)
    prose_chars = sum(len(unit) for unit in units)
    navigation = looks_like_navigation(body)
    evidence: dict[str, Any] = {
        "chars": len(body), "prose_chars": prose_chars, "prose_blocks": len(units),
        "prose_share": round(prose_chars / len(body), 2),
        "looks_like_navigation": navigation}
    if navigation:
        evidence["reason"] = "link_farm"
        return "navigation", evidence
    # An item/category page is a next hop, never a claim window - but only when prose is
    # scarce. A real article that happens to contain a list keeps its substance.
    if looks_like_list(body) and evidence["prose_share"] < LIST_PROSE_SHARE:
        evidence["reason"] = "item_list"
        return "navigation", evidence
    if len(units) >= MIN_PROSE_SENTENCES and prose_chars >= MIN_PROSE_CHARS:
        evidence["reason"] = "prose_sentences"
        return "substantive", evidence
    evidence["reason"] = "no_prose"
    return "unusable", evidence


def _is_locale_segment(segment: str) -> bool:
    return bool(segment) and bool(_LOCALE_RE.fullmatch(segment))


def classify_page(url: str, anchor: str = "", context: str = "") -> str:
    """Classify a link target as article / category / home / uncertain.

    Pure URL+text heuristics: a directory page must never look like a正文, and a
    site root must never be offered as the answer.
    """
    path = unquote(urlsplit(url or "").path or "/")
    segments = [seg for seg in path.split("/") if seg]
    text = f"{anchor} {context}"
    if not segments:
        return "home"
    if len(segments) == 1 and _is_locale_segment(segments[0]):
        return "home"
    if _CATEGORY_WORD_RE.search(text) or _CATEGORY_WORD_RE.search(segments[-1].replace("-", " ")):
        return "category"
    if path.endswith("/") and len(segments) <= 2:
        return "category"
    last = segments[-1]
    if re.search(r"[-_]", last) or (len(last) >= 8 and last.isascii()) or re.search(r"[a-z][A-Z]", last):
        return "article"
    if len(segments) >= 2:
        return "article"
    return "uncertain"


def _noise_reason(anchor: str, path: str, url: str, repeated: int) -> str:
    anchor = (anchor or "").strip()
    segments = [seg for seg in (path or "").split("/") if seg]
    if _LOGIN_RE.search(anchor):
        return "login"
    if _BOILERPLATE_RE.search(anchor) or _BOILERPLATE_RE.search(path):
        return "boilerplate"
    if _LANGUAGE_NAME_RE.fullmatch(anchor):
        return "language"
    if segments and _is_locale_segment(segments[0]) and not any(
        _LANGUAGE_NAME_RE.fullmatch(seg) for seg in segments[1:]
    ):
        return "language"
    if anchor and _LOCALE_RE.fullmatch(anchor):
        return "language"
    if repeated >= 4:
        return "repeated_navigation"
    return ""


def _nearest_heading(node, limit: int = 3) -> str:
    """Text of the nearest preceding heading, looking up at most ``limit`` levels."""
    current = node
    for _ in range(limit):
        if current is None:
            break
        previous = current.getprevious()
        while previous is not None:
            tag = getattr(previous, "tag", None)
            if isinstance(tag, str) and tag.lower() in ("h1", "h2", "h3", "h4"):
                text = " ".join(previous.itertext()).strip()
                if text:
                    return text[:120]
            found = previous.xpath(".//h1|.//h2|.//h3|.//h4")
            if found:
                text = " ".join(found[0].itertext()).strip()
                if text:
                    return text[:120]
            previous = previous.getprevious()
        current = current.getparent()
    return ""


def extract_candidates(
    html: str,
    base_url: str,
    *,
    max_links: int = MAX_LINKS,
) -> list[Candidate]:
    """Same-origin candidates from ONE page, with anchor, path and heading context.

    Fragments, non-http schemes, cross-origin targets and duplicate URLs are
    dropped. Never raises on malformed HTML: an unparsable document yields [].
    """
    if not html:
        return []
    if len(html) > MAX_HTML_BYTES:
        html = html[:MAX_HTML_BYTES]
    try:
        root = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - malformed document is not fatal
        try:
            root = lxml_html.document_fromstring(html)
        except Exception:  # noqa: BLE001
            return []
    base_host = (urlsplit(base_url).hostname or "").lower()
    seen: set[str] = set()
    anchors_seen: dict[str, int] = {}
    out: list[Candidate] = []
    for anchor_el in root.iter("a"):
        href = (anchor_el.get("href") or "").strip()
        if not href or href.startswith(_SKIP_PREFIXES):
            continue
        resolved = urljoin(base_url, href)
        parts = urlsplit(resolved)
        if parts.scheme not in ("http", "https"):
            continue
        if (parts.hostname or "").lower() != base_host:
            continue
        key = resolved.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        anchor_text = " ".join(anchor_el.itertext()).strip()[:120]
        anchors_seen[anchor_text] = anchors_seen.get(anchor_text, 0) + 1
        out.append(
            Candidate(
                url=key,
                anchor=anchor_text,
                path=unquote(parts.path or ""),
                context=_nearest_heading(anchor_el),
            )
        )
        if len(out) >= max_links:
            break
    for candidate in out:
        candidate.repeated = anchors_seen.get(candidate.anchor, 0)
    return out


def rank_candidates(
    candidates: list[Candidate],
    terms: set[str],
    *,
    limit: int = 10,
    question: str = "",
) -> list[Candidate]:
    """Rank candidates by question relevance, then page type, then document order.

    Deterministic: identical inputs always produce the same order. The result is
    what the model is offered, so every entry carries its score, type and a short
    ``why`` string the model can reason about.
    """
    if not candidates:
        return []
    # Rare query terms are stronger signals than common ones: weight each term by
    # how few same-page candidates mention it. Computed over this page only.
    mentions = {term: 0 for term in terms}
    for probe in candidates:
        hay = f"{probe.anchor} {probe.path}".lower()
        for term in terms:
            if term in hay:
                mentions[term] += 1
    total = len(candidates)
    weights = {
        term: (1.0 + total / count) if count else 0.0
        for term, count in mentions.items()
    }
    for index, candidate in enumerate(candidates):
        candidate.page_type = classify_page(candidate.url, candidate.anchor, candidate.context)
        hay_anchor = candidate.anchor.lower()
        hay_path = candidate.path.lower().replace("-", " ").replace("_", " ")
        hay_context = candidate.context.lower()
        matched: set[str] = set()
        score = 0.0
        for term in terms:
            weight = weights.get(term, 0.0)
            if not weight:
                continue
            if term in hay_anchor:
                score += 3.0 * weight
                matched.add(term)
            elif term in hay_path:
                score += 1.0 * weight
                matched.add(term)
            elif term in hay_context:
                score += 0.5 * weight
                matched.add(term)
        coverage = len(matched) / len(terms) if terms else 0.0
        prior = {"article": 1.5, "category": 1.0, "home": -3.0, "uncertain": 0.0}
        base_prior = prior.get(candidate.page_type, 0.0)
        if base_prior < 0:
            score += base_prior            # a site root is never the answer
        elif matched:
            score += base_prior * coverage  # being an article is not evidence of relevance
        if candidate.path.count("/") > 0:
            score += 0.2
        noise = _noise_reason(
            candidate.anchor,
            candidate.path,
            candidate.url,
            candidate.repeated,
        )
        if noise:
            score -= 5.0
        candidate.score = score
        candidate.matched = frozenset(matched)
        bits = []
        if matched:
            bits.append("matches " + "+".join(sorted(matched)[:4]))
            bits.append("coverage %.2f" % coverage)
        bits.append(candidate.page_type)
        if noise:
            bits.append("noise:" + noise)
        candidate.why = "; ".join(bits)
        candidate.order = index
    # Specificity: when one candidate matches strictly more of the question than
    # another, the broader page is "same domain" rather than the question itself
    # (中继器 ⊃ 红石, Train interrupts ⊃ Train). Rank the narrower, more specific
    # target above the broader one instead of relying on the [article] label.
    for candidate in candidates:
        if not candidate.matched:
            continue
        if any(other is not candidate and candidate.matched < other.matched
               for other in candidates):
            candidate.score -= 1.0
            candidate.why += "; broader than a more specific match"
    ranked = sorted(
        candidates,
        key=lambda c: (c.score, -c.order),
        reverse=True,
    )
    # Display diversity last: one navigation family must not take every shown slot.
    ranked = diversify_navigation_families(ranked, question=question)
    return ranked[:limit]
