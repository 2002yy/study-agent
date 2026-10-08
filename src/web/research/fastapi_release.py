"""Exact release-heading projection at the trusted FastAPI HTML read boundary.

The version query is a local reader selector, not a server API or date claim.
Only the official release-notes article's unique h2 record supplies the date.
"""

from __future__ import annotations

from datetime import date
import hashlib
import re
from typing import Any

from lxml import html  # type: ignore[import-untyped]

from src.web.research.evidence_binding import document_from_read

BASE_URL = "https://fastapi.tiangolo.com/release-notes/"


def selected_version(url: str) -> str | None:
    match = re.fullmatch(re.escape(BASE_URL) + r"\?version=(\d+\.\d+\.\d+)", url)
    return match[1] if match else None


def release_fields(
    url: str, payload: bytes, bindings: dict[str, Any] | None
) -> dict[str, str]:
    version = selected_version(url)
    if version is None:
        raise ValueError("fastapi_exact_selector_required")
    tree = html.fromstring(payload)
    titles = tree.xpath("//title")
    articles = tree.xpath("//article")
    if (
        len(titles) != 1
        or not re.fullmatch(
            r"Release Notes\s*[-–]\s*FastAPI", titles[0].text_content().strip()
        )
        or len(articles) != 1
    ):
        raise ValueError("fastapi_release_page_identity_mismatch")
    article = articles[0]
    headings = article.xpath("./h1")
    if (
        len(headings) != 1
        or headings[0].text_content().strip().rstrip("¶").strip() != "Release Notes"
    ):
        raise ValueError("fastapi_release_page_identity_mismatch")
    # TOC links, prose, nested headings and neighbouring versions cannot bind.
    nodes = [
        node
        for node in article.xpath("./h2")
        if re.match(re.escape(version) + r"(?=\s|\(|$)", node.text_content().strip())
    ]
    if len(nodes) != 1:
        raise ValueError("fastapi_release_record_missing_or_ambiguous")
    node = nodes[0]
    heading = node.text_content().strip().rstrip("¶").strip()
    match = re.fullmatch(re.escape(version) + r" \((\d{4}-\d{2}-\d{2})\)", heading)
    if match is None:
        raise ValueError("fastapi_release_date_heading_invalid")
    value = date.fromisoformat(match[1]).isoformat()
    anchor = version.replace(".", "") + "-" + value
    if node.get("id") != anchor:
        raise ValueError("fastapi_release_anchor_mismatch")
    document = document_from_read(
        hashlib.sha256(payload).hexdigest(), BASE_URL, payload
    )
    sections = [
        section
        for section in document.sections
        if document.text[section.heading_start : section.heading_end]
        .strip()
        .rstrip("¶")
        .strip()
        == heading
    ]
    if len(sections) != 1:
        raise ValueError("fastapi_release_span_ambiguous")
    section = sections[0]
    start, end = section.heading_start, section.heading_end
    if bindings is not None:
        proof = {
            "kind": "fastapi_official_release_heading",
            "product": "fastapi",
            "version": version,
            "url": BASE_URL,
            "record_url": BASE_URL + "#" + anchor,
            "read_id": document.read_id,
            "decoded_payload_sha256": document.payload_sha256,
            "source_content_sha256": document.content_sha256,
            "heading_span": [start, end],
            "heading_quote": document.text[start:end],
            "source_span": [start, end],
            "quote": document.text[start:end],
        }
        for field in ("project", "version", "release_date"):
            bindings[field] = {**proof, "field": field}
    return {"project": "FastAPI", "version": version, "release_date": value}
