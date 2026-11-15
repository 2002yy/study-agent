"""Which sources an answer is allowed to cite.

Verification can only check pages the turn actually read. A model that writes a
plausible citation from memory therefore produces a link nobody can verify, and
the binder rejects the whole answer. The cheaper, earlier rule is: an answer may
cite only sources that are already in the evidence set.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit

_URL = re.compile(r"https?://[^\s<>()\[\]\"'，。；）】]+", re.IGNORECASE)


def normalize_link(url: str) -> str:
    """Scheme-insensitive, ``www.``-insensitive identity of a page."""

    raw = str(url or "").strip().rstrip(".,;:!?")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}"


def links_in_answer(answer: str) -> list[str]:
    return [match.group(0) for match in _URL.finditer(str(answer or ""))]


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
        if not normalized or normalized in allowed or normalized in seen:
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
]
