"""Bounded, source-transparent discovery from known official documentation indexes.

The index is a directory of candidate links, never answer evidence. Its HTML
is fetched by the existing SSRF-safe transport. Every selected child still
needs an ordinary, discovery-linked ``web_read`` before it can be cited.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from src.news.article_fetcher import _fetch_html_payload


# Verified index entry points, not guessed answer URLs. Add another host only
# after confirming it exposes a real link directory with readable child pages.
OFFICIAL_DOCUMENT_INDEXES = {"sqlite.org": "https://sqlite.org/docs.html"}
INDEX_TIMEOUT_SECONDS = 1.8
_MAX_INDEX_BYTES = 256 * 1024
_MAX_INDEX_LINKS = 1000
_STOPWORDS = frozenset({
    "sqlite", "postgresql", "postgres", "database", "online", "official",
    "documentation", "docs", "api", "the", "and", "for", "with", "from",
    "how", "what", "which", "does", "are", "can", "using", "use", "that",
    "this", "when", "without", "long", "running", "file", "system",
})


def _host(value: str) -> str:
    host = (urlsplit(value).hostname or "").casefold()
    return host.removeprefix("www.")


class _IndexAnchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and len(self.links) < _MAX_INDEX_LINKS:
            self.href = next((value for name, value in attrs if name == "href"), None)
            self.text = []

    def handle_data(self, data: str) -> None:
        if self.href is not None and sum(map(len, self.text)) < 200:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(" ".join(self.text).split())[:200]))
            self.href = None
            self.text = []


def _facet_terms(domain: str, query: str) -> set[str]:
    text = query.casefold()
    terms = {
        word for word in re.findall(r"[a-z][a-z0-9-]{2,}", text)
        if word not in _STOPWORDS
    }
    if re.search(r"备份|恢复|backup|restore", text):
        terms.add("backup")
    if domain == "sqlite.org":
        # WAL is where SQLite documents checkpoint starvation and why its
        # shared-memory mechanism is unsuitable for cross-host NFS writers.
        if re.search(r"长事务|读事务|检查点|网络文件系统|checkpoint|nfs|network.file.system|long.running", text):
            terms.add("wal")
    return terms


def has_facet_document(
    items: list[dict[str, str]], *, domain: str, facet_query: str,
) -> bool:
    """Did discovery already find a topic-specific official *document*?

    A generic homepage/index/download result must not suppress index fallback.
    This is a discovery heuristic, not a statement that any fact is supported.
    """

    terms = _facet_terms(domain, facet_query)
    for item in items:
        url = str(item.get("url") or "")
        path = urlsplit(url).path.casefold()
        if _host(url) != domain or not path.endswith((".html", ".htm")):
            continue
        if path.rsplit("/", 1)[-1] in {"index.html", "docs.html", "download.html"}:
            continue
        # The title/body of WAL docs may mention "backup" in passing. That
        # does NOT mean the dedicated backup facet has been read; require a
        # topic-specific path before suppressing the directory lookup.
        words = set(re.findall(r"[a-z][a-z0-9-]{2,}", path))
        if terms & words:
            return True
    return False


def parse_official_index_links(
    html: str, *, index_url: str, domain: str, facet_query: str, limit: int = 2,
) -> list[dict[str, str]]:
    """Return only existing same-host HTML links relevant to a question facet."""

    if _host(index_url) != domain or not html:
        return []
    terms = _facet_terms(domain, facet_query)
    if not terms:
        return []
    parser = _IndexAnchors()
    try:
        parser.feed(html[:_MAX_INDEX_BYTES])
    except (ValueError, TypeError):
        return []
    ranked: list[tuple[int, int, dict[str, str]]] = []
    seen: set[str] = set()
    for position, (href, title) in enumerate(parser.links):
        try:
            candidate = urljoin(index_url, href)
            parts = urlsplit(candidate)
            port = parts.port
            same_host = _host(candidate) == domain
        except ValueError:
            continue
        if (parts.scheme != "https" or not same_host
                or parts.username or parts.password or port not in {None, 443}):
            continue
        if not parts.path.lower().endswith((".html", ".htm")):
            continue
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if url == index_url or url in seen:
            continue
        seen.add(url)
        target_words = set(re.findall(r"[a-z][a-z0-9-]{2,}", f"{title} {parts.path}".casefold()))
        score = len(terms & target_words)
        if score:
            ranked.append((-score, position, {
                "title": title or parts.path.rsplit("/", 1)[-1],
                "url": url,
                "snippet": f"Official documentation index: {index_url}",
            }))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in ranked[:max(1, min(int(limit), 3))]]


def discover_official_index(
    domain: str, facet_query: str, *, timeout: float = INDEX_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Fetch one allowlisted directory using existing safe HTTP, with no LLM."""

    index_url = OFFICIAL_DOCUMENT_INDEXES.get(domain)
    if not index_url:
        return {"status": "not_configured", "results": []}
    try:
        html, final_url, _, reason = _fetch_html_payload(
            index_url, timeout=max(0.1, min(timeout, INDEX_TIMEOUT_SECONDS)),
            max_bytes=_MAX_INDEX_BYTES,
        )
    except Exception as exc:
        return {"status": "unavailable", "index_url": index_url,
                "reason": type(exc).__name__, "results": []}
    # A redirect away from the official host is not an index of that host.
    if reason or _host(final_url) != domain:
        return {"status": "unavailable", "index_url": index_url,
                "reason": reason or "off_domain_redirect", "results": []}
    return {"status": "ok", "index_url": index_url,
            "html": html,
            "results": parse_official_index_links(
                html, index_url=final_url, domain=domain, facet_query=facet_query,
            )}
