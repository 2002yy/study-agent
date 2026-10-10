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
from urllib.parse import unquote, urljoin, urlsplit

from lxml import html as lxml_html  # type: ignore[import-untyped]

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
    return ranked[:limit]
