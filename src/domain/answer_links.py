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


__all__ = [
    "links_in_answer",
    "normalize_link",
    "outside_evidence_links",
]
