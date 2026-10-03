"""§63/§65/§66 Tier-1.5 domain-targeted retrieval: canonical targets + sitemap.

The missing capability behind §44/§51/§52: the effective Tier-1 provider (Bing
RSS) never returns deep official pages. This channel asks the model only for
**canonical targets** (host + scope + a model-declared role), then uses
deterministic machinery on top of the existing fetch layer:

    claim -> model: <=2 canonical targets
          -> accept official / project-host, reject third-party
          -> deterministic inventory URLs (/sitemap.xml, /sitemap_index.xml)
          -> parse <loc> entries (one sitemapindex level, bounded children)
          -> rank same-domain URLs by claim-term overlap in the path
          -> reader verification (ok + non-empty) -> candidate
          -> existing assessment -> extraction -> Gate

Contract (§66/B1-T2):

    {"targets": [
        {"host": "postgresql.org",
         "scope": "https://www.postgresql.org/",
         "domain_role": "official"}
    ]}

- ``domain_role`` is a **model-declared classification**, not verified truth:
  it is carried internally as ``proposed_domain_role`` and must never be read
  as server-verified official status. No verifier exists in this batch.
- ``official``: the publisher *is* the project/entity (postgresql.org,
  nodejs.org, docs.docker.com, docs.astral.sh).
- ``project-host``: canonical upstream on a general hosting platform
  (``https://github.com/astral-sh/uv/``); its scope must point at the project,
  never at the bare host root.
- ``third-party``: everything else (trackers, mirrors, blogs, community sites)
  - correct information does not make a site official.

Why sitemaps and not site search: a cross-site probe over eight documentation
hosts found the ``/search/?q=`` shapes returning 404 on 7/8 and, where they
returned 200, the root page with the query ignored. Sitemaps are the general
surface where present (docs.docker.com serves 1811 <loc> entries including the
deep target).

Candidates carry ``discovery_method="domain_targeted"`` so provenance stays
separate from ``search`` and ``llm_proposed``. Default off
(``RESEARCH_DOMAIN_TARGETED=on``); nothing here can create evidence.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

DOMAIN_TARGETED_ENV = "RESEARCH_DOMAIN_TARGETED"
DISCOVERY_METHOD_DOMAIN_TARGETED = "domain_targeted"
# Accepted targets are capped at MAX_DOMAINS; the parsed audit list is bounded
# separately so a declared third-party target can never truncate a valid
# official one out of the contract check.
MAX_DOMAINS = 2
MAX_TARGETS_PARSED = 4
MAX_SITEMAP_URLS = 2
MAX_SITEMAP_CHILDREN = 2
MAX_LINKS_PER_INVENTORY = 5
MAX_SEARCH_TERMS = 6
MAX_RANK_TERMS = 12

DOMAIN_ROLES = ("official", "project-host", "third-party")
ACCEPTED_DOMAIN_ROLES = ("official", "project-host")

DOMAIN_SYSTEM_PROMPT = (
    "You are a web-research planner. Given a claim, name up to 2 **canonical "
    "targets** that would publish the needed fact, most likely first. Reply "
    "with strict JSON:\n"
    '{"targets": [{"host": "example.org", "scope": "https://example.org/docs/", '
    '"domain_role": "official"}]}\n'
    "Rules:\n"
    "- host: bare host only (no scheme, no path, no trailing slash).\n"
    "- scope: an https URL inside that host that bounds where to look.\n"
    "- domain_role: 'official' when the publisher IS the project/entity "
    "(vendor docs, official project site); 'project-host' when the canonical "
    "upstream lives on a general hosting platform and scope points at the "
    "project (e.g. https://github.com/astral-sh/uv/), never the bare host "
    "root; 'third-party' for trackers, mirrors, blogs, community or news "
    "sites even when their information is correct.\n"
    "- Prefer 'official' targets; at most 2 targets."
)

_STOPWORDS = frozenset(
    {
        "what", "which", "when", "where", "who", "how", "does", "do", "did",
        "is", "are", "was", "were", "the", "a", "an", "of", "for", "to", "in",
        "on", "at", "and", "or", "with", "by", "from", "that", "this", "it",
        "its", "as", "be", "has", "have", "under", "per", "into", "about",
        # Chinese function words (claims may be bilingual)
        "的", "了", "是", "在", "和", "与", "有", "对", "为", "个", "什么",
    }
)

_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_CHILD_HINTS = ("page", "route", "doc")


def domain_targeted_enabled() -> bool:
    raw = (os.getenv(DOMAIN_TARGETED_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def normalize_host(value: Any) -> str:
    """Bare lowercase host from a host string or URL; "" when unusable."""

    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^[a-z]+://", "", text)
    text = text.split("/")[0].split("?")[0].strip(".")
    if "@" in text:
        text = text.rsplit("@", 1)[-1]
    if ":" in text:
        text = text.split(":", 1)[0]
    if text.startswith("www."):
        text = text[4:]
    if not text or "." not in text or " " in text:
        return ""
    return text


@dataclass(frozen=True)
class DomainTarget:
    """One model-declared canonical target.

    ``proposed_domain_role`` is a *declaration*, not verified truth; the runtime
    only checks it against the accepted enum plus the project-host scope rule.
    Every structurally parseable declaration is kept (with a ``reject_reason``)
    so the audit shows what the model actually claimed instead of silently
    dropping it.
    """

    host: str
    scope: str
    proposed_domain_role: str

    @property
    def accepted(self) -> bool:
        return not self.reject_reason

    @property
    def reject_reason(self) -> str:
        if self.proposed_domain_role not in DOMAIN_ROLES:
            return "unsupported_role"
        if self.proposed_domain_role == "third-party":
            return "third_party"
        if not self.scope:
            return "invalid_scope"
        if self.proposed_domain_role == "project-host":
            path = urlparse(self.scope).path or "/"
            if not path.strip("/"):
                return "project_host_scope_too_broad"
        return ""

    def to_record(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "scope": self.scope,
            "proposed_domain_role": self.proposed_domain_role,
            "accepted": self.accepted,
            "reject_reason": self.reject_reason,
        }


def _parse_scope(raw: Any, *, host: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return f"https://{host}/"
    parsed = urlparse(text)
    if parsed.scheme != "https":
        return ""
    scope_host = normalize_host(parsed.netloc)
    if not scope_host or not scope_host.endswith(host):
        return ""
    return text


def parse_domain_proposal(raw: Any) -> list[DomainTarget]:
    """Strict parser: object with a targets list of {host, scope, domain_role}.

    Structural problems raise (the caller records the failure). Per-entry
    problems are preserved as rejected declarations with a machine-checkable
    ``reject_reason`` (unsupported_role / third_party / invalid_scope /
    project_host_scope_too_broad) so the audit can distinguish "the model never
    proposed it" from "the contract refused it". Output is deduplicated and
    bounded; the accepted cap is applied by the runtime.
    """

    if not isinstance(raw, Mapping):
        raise ValueError("domain proposal must be an object")
    targets = raw.get("targets")
    if not isinstance(targets, list):
        raise ValueError("domain proposal needs a targets list")
    cleaned: list[DomainTarget] = []
    seen: set[tuple[str, str]] = set()
    for item in targets:
        if not isinstance(item, Mapping):
            continue
        host = normalize_host(item.get("host"))
        if not host:
            continue
        role = str(item.get("domain_role") or "").strip().lower()
        scope = _parse_scope(item.get("scope"), host=host)
        key = (host, scope.rstrip("/") or role)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(
            DomainTarget(host=host, scope=scope, proposed_domain_role=role)
        )
        if len(cleaned) >= MAX_TARGETS_PARSED:
            break
    return cleaned


def accepted_targets(targets: Iterable[DomainTarget]) -> list[DomainTarget]:
    return [target for target in targets if target.accepted]


def claim_search_terms(claim_text: str, *, limit: int = MAX_SEARCH_TERMS) -> list[str]:
    """Significant terms of the claim, order-preserving and bounded."""

    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9+._-]*|[\u4e00-\u9fff]{2,}", str(claim_text or ""))
    terms: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in _STOPWORDS or len(lowered) < 2:
            continue
        if lowered not in terms:
            terms.append(lowered)
        if len(terms) >= max(1, int(limit)):
            break
    return terms


def build_search_query(claim_text: str) -> str:
    return " ".join(claim_search_terms(claim_text))


def sitemap_urls(host: str, *, max_paths: int = MAX_SITEMAP_URLS) -> list[str]:
    """Deterministic sitemap locations for one canonical host."""

    normalized = normalize_host(host)
    if not normalized:
        return []
    base = f"https://{normalized}"
    return [base + path for path in _SITEMAP_PATHS[: max(1, int(max_paths))]]


def parse_sitemap(text: str) -> tuple[str, list[str]]:
    """Return (kind, locations) where kind is 'index', 'urlset', or 'empty'."""

    if not text:
        return "empty", []
    locations = _LOC_RE.findall(text)
    head = text[:2000].lower()
    if "<sitemapindex" in head:
        return "index", locations
    if locations:
        return "urlset", locations
    return "empty", []


def prioritise_sitemap_children(
    children: Iterable[str], *, limit: int = MAX_SITEMAP_CHILDREN
) -> list[str]:
    """Pick the most documentation-likely children of a sitemapindex."""

    ranked: list[tuple[int, str]] = []
    for child in children:
        lowered = child.lower()
        score = sum(1 for hint in _CHILD_HINTS if hint in lowered)
        if any(bad in lowered for bad in ("blog", "news", "press", "event")):
            score -= 2
        ranked.append((-score, lowered))
    ranked.sort()
    return [child for _score, child in ranked[: max(1, int(limit))]]


class _AnchorExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def _stem(token: str) -> str:
    """Naive plural stem so 'limits'/'limit' and 'pulls'/'pull' collapse."""

    return token[:-1] if len(token) > 4 and token.endswith("s") else token


def _stems(value: str) -> set[str]:
    """Lowercased alphanumeric stems of a string (path or term list)."""

    return {
        _stem(part)
        for part in re.findall(r"[a-z0-9]+", value.lower())
        if len(part) >= 2
    }


def rank_domain_urls(
    urls: Iterable[str],
    *,
    domain: str,
    terms: Iterable[str],
    limit: int = MAX_LINKS_PER_INVENTORY,
) -> list[str]:
    """Same-domain URLs ranked by claim-term overlap in the path.

    Scoring counts distinct matched stems (with plural collapse, so
    "limits"/"limit" count once). Distinct-match counting was chosen over
    inverse-document-frequency weighting on evidence: idf over-rewards rare but
    semantically empty words ("official", "current") that appear in a claim's
    preamble, whereas a plain count rewards paths that match several claim
    stems at once - exactly the deep page here (`docker` + `hub` + `pull`).
    Ties break towards shallower paths, then lexicographically.
    """

    host = normalize_host(domain)
    if not host:
        return []

    term_stems: set[str] = set()
    for term in terms:
        term_stems |= _stems(str(term or ""))

    documents: list[tuple[str, str, set[str]]] = []
    seen: set[str] = set()
    for raw in urls:
        parsed = urlparse(str(raw or "").strip())
        if parsed.scheme != "https" or not parsed.netloc.lower().endswith(host):
            continue
        path = (parsed.path or "/").lower()
        if not path.strip("/"):
            continue
        normalized = f"https://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
        if normalized in seen:
            continue
        seen.add(normalized)
        documents.append((normalized, path, _stems(path)))

    if not documents or not term_stems:
        return []

    scored: list[tuple[float, int, str]] = []
    for url, path, stems in documents:
        matched = stems & term_stems
        if not matched:
            continue
        scored.append((-float(len(matched)), path.count("/"), url))
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [url for _neg, _depth, url in scored[: max(1, int(limit))]]


def extract_candidate_links(
    html: str,
    *,
    domain: str,
    terms: Iterable[str],
    limit: int = MAX_LINKS_PER_INVENTORY,
    page_url: str = "",
) -> list[str]:
    """Same-domain anchors ranked by claim-term overlap in the URL path.

    Kept for HTML inventories (hub/nav pages) alongside sitemap harvesting.
    """

    host = normalize_host(domain)
    if not host or not html:
        return []
    parser = _AnchorExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []
    base = page_url or f"https://{host}/"
    absolute_urls: list[str] = []
    for href in parser.hrefs:
        if href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        absolute_urls.append(urljoin(base, href))
    return rank_domain_urls(absolute_urls, domain=host, terms=terms, limit=limit)


def domain_proposal_payload(claim_text: str) -> dict[str, str]:
    return {"claim": str(claim_text or "")[:2000]}


def domain_proposal_messages(claim_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": DOMAIN_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                domain_proposal_payload(claim_text), ensure_ascii=False
            ),
        },
    ]


__all__ = [
    "ACCEPTED_DOMAIN_ROLES",
    "DISCOVERY_METHOD_DOMAIN_TARGETED",
    "DOMAIN_ROLES",
    "DOMAIN_SYSTEM_PROMPT",
    "DOMAIN_TARGETED_ENV",
    "DomainTarget",
    "MAX_DOMAINS",
    "MAX_LINKS_PER_INVENTORY",
    "MAX_RANK_TERMS",
    "MAX_SITEMAP_CHILDREN",
    "MAX_SITEMAP_URLS",
    "MAX_TARGETS_PARSED",
    "accepted_targets",
    "build_search_query",
    "claim_search_terms",
    "domain_proposal_messages",
    "domain_proposal_payload",
    "domain_targeted_enabled",
    "extract_candidate_links",
    "normalize_host",
    "parse_domain_proposal",
    "parse_sitemap",
    "prioritise_sitemap_children",
    "rank_domain_urls",
    "sitemap_urls",
]
