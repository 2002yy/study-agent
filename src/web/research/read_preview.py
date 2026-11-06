"""Display-only, bounded excerpts from *completed reads*, never answer authority.

This projection must not be mixed into source_block, assistant_message,
assertion_refs, official field publication, or research confidence.
"""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from src.web.research.read_evidence import read_excerpt
from src.web.tool_evidence import _public_url


def unverified_read_previews(selected_sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    """At most two attributed snippets; discovery snippets are never reads."""
    previews: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in selected_sources:
        if not isinstance(record, dict):
            continue
        item, assessment, read = (
            record.get("item"), record.get("assessment"), record.get("read")
        )
        if not all(isinstance(v, dict) for v in (item, assessment, read)):
            continue
        if assessment.get("selected") is not True or assessment.get("worth_reading") is not True:
            continue
        if read.get("status") != "read" or read.get("ok") is not True:
            continue
        if read.get("error") or read.get("answer_eligible") is False:
            continue
        requested = _public_url(
            assessment.get("url") or item.get("url") or item.get("link")
        )
        actual = _public_url(read.get("url") or requested)
        if not requested or not actual:
            continue
        if read.get("requested_url") and read["requested_url"] != requested:
            continue
        # A read may legitimately redirect, but not from one named site to a
        # completely unrelated one without a new attribution in this preview.
        if urlsplit(actual).hostname != urlsplit(requested).hostname:
            continue
        if requested in seen:
            continue
        excerpt = read_excerpt(read)
        # A directory listing or search snippet is not a quoted page excerpt.
        if not excerpt or not isinstance(read.get("content") or read.get("readme"), str):
            continue
        digest = read.get("excerpt_sha256")
        if digest and digest != hashlib.sha256(excerpt.encode("utf-8")).hexdigest():
            continue
        quote = " ".join(excerpt.split())[:240]
        if not quote:
            continue
        title = " ".join(str(item.get("title") or actual).split())[:120]
        previews.append({
            "url": actual, "title": title, "excerpt": quote,
            "read_id": str(read.get("read_id") or "")[:40],
            "kind": "read_excerpt_unverified",
        })
        seen.add(requested)
        if len(previews) == 2:
            break
    return previews
