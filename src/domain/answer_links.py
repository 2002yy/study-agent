"""Which sources an answer is allowed to cite.

Verification can only check pages the turn actually read. A model that writes a
plausible citation from memory therefore produces a link nobody can verify.
The cheaper, earlier rule is: an answer may cite only sources that are already
in the evidence set. The gate removes an unsupported link locally and labels
the result, instead of discarding the whole answer.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit

_URL = re.compile(r"https?://[^\s<>()\[\]\"'，。；）】]+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", re.IGNORECASE)
#: Citation labels that carry no meaning once the link is removed.
_BARE_LABEL = re.compile(
    r"(?:来源|source|link|链接|参考|ref(?:erence)?)\s*\d*", re.IGNORECASE
)


def normalize_link(url: str) -> str:
    """Page identity, retaining content-selecting query parameters.

    Tracking parameters do not change which page was read, but ``?id=1`` and
    ``?id=2`` can be entirely different documents and must not be conflated.
    """

    raw = str(url or "").strip().rstrip(".,;:!?")
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").casefold()
        port = parsed.port
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    if port is not None and (parsed.scheme.lower(), port) not in {
        ("https", 443), ("http", 80)
    }:
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
    ))
    return f"{host}{path}" + (f"?{query}" if query else "")


def links_in_answer(answer: str) -> list[str]:
    return [match.group(0) for match in _URL.finditer(str(answer or ""))]


def strip_outside_links(
    answer: str, evidence_urls: Iterable[str]
) -> tuple[str, list[str]]:
    """Remove citations to pages this turn did not read.

    The claim stays; only the unsupported citation disappears. A citation label
    such as ``[来源]`` is meaningless without its link, so that token is dropped
    whole; a descriptive label (``[官方 README]``) is kept as plain text. The
    caller records the removed URLs so the answer is not presented as verified.
    """

    allowed = {
        normalized
        for normalized in (normalize_link(url) for url in evidence_urls)
        if normalized
    }
    removed: list[str] = []

    def replace_markdown(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        if normalize_link(url) in allowed:
            return match.group(0)
        removed.append(url)
        label = label.strip()
        if not label or _BARE_LABEL.fullmatch(label):
            return ""
        return label

    text = _MARKDOWN_LINK.sub(replace_markdown, str(answer or ""))

    def replace_bare(match: re.Match[str]) -> str:
        url = match.group(0)
        if normalize_link(url) in allowed:
            return url
        removed.append(url)
        return ""

    text = _URL.sub(replace_bare, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), removed


def outside_evidence_links(
    answer: str, evidence_urls: Iterable[str]
) -> list[str]:
    """Answer links whose page is not part of the read evidence."""

    allowed = {
        normalized
        for normalized in (normalize_link(url) for url in evidence_urls)
        if normalized
    }
    outside: list[str] = []
    seen: set[str] = set()
    for link in links_in_answer(answer):
        normalized = normalize_link(link)
        if normalized in allowed or normalized in seen:
            continue
        seen.add(normalized)
        outside.append(link)
    return outside


def classify_outside_links(
    answer: str, evidence_urls: Iterable[str]
) -> list[dict[str, str]]:
    """Why a cited page is unacceptable, not just that it is.

    "The page exists but this turn never read it" (a search-coverage gap) is a
    different failure from "the model named a host nobody looked at" (a memory
    citation). They warrant different follow-up work, so they are reported apart.
    """

    evidence = [str(url) for url in evidence_urls if str(url or "").strip()]
    evidence_hosts = {normalize_link(url).split("/")[0] for url in evidence}
    classified: list[dict[str, str]] = []
    for link in outside_evidence_links(answer, evidence):
        host = normalize_link(link).split("/")[0]
        classified.append({
            "url": link,
            "kind": "read_host_page_not_read" if host in evidence_hosts
            else "host_not_in_evidence",
        })
    return classified


__all__ = [
    "classify_outside_links",
    "links_in_answer",
    "normalize_link",
    "outside_evidence_links",
    "strip_outside_links",
]
