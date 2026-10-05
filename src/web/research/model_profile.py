"""Narrow official model profile: exact page, heading, ID and bound intro quote.

This adapter publishes the official positioning verbatim, never capabilities,
benchmark interpretation or comparisons from the rest of a mixed-content page.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from src.web.research.evidence_binding import EvidenceProposal, document_from_read, verify_binding
from src.web.research.identity import identities_in_text, resolve_identity


_URL = re.compile(r"https://platform\.claude\.com/docs/en/models/opus-(\d+-\d+(?:-\d+)?)/overview")
_MODEL_ID = re.compile(r"(?<![\w.+-])claude-opus-[\w.+-]+(?![\w.+-])")


def profile_fields(url: str, payload: bytes, source_bindings: dict[str, Any] | None) -> dict[str, str]:
    match = _URL.fullmatch(url)
    identity = resolve_identity("opus", match[1].replace("-", ".")) if match else None
    if identity is None:
        raise ValueError("model_profile_url_identity_missing")
    from lxml import html  # type: ignore[import-untyped]

    titles = html.fromstring(payload).xpath("//h1")
    title = " ".join(" ".join(titles[0].itertext()).split()) if len(titles) == 1 else ""
    if (not re.fullmatch(r"Claude Opus \d+(?:\.\d+)+(?: Latest)?", title, re.I)
            or identities_in_text(title) != (identity,)):
        raise ValueError("model_profile_title_identity_mismatch")
    document = document_from_read(hashlib.sha256(payload).hexdigest(), url, payload)
    # Exactly one product heading; a side heading or mixed overview cannot
    # become the main version anchor. Cookie/navigation headings are ignored.
    sections = [section for section in document.sections
                if re.match(r"\s*Claude\s+Opus\b", document.text[section.heading_start:section.heading_end], re.I)]
    if len(sections) != 1:
        raise ValueError("model_profile_heading_ambiguous")
    section = sections[0]
    heading = document.text[section.heading_start:section.heading_end]
    if identities_in_text(heading) != (identity,):
        raise ValueError("model_profile_heading_identity_mismatch")
    # IDs in other sections, navigation, scripts and comparison tables cannot
    # corroborate this heading. Full tokens never truncate extended IDs.
    ids = list(_MODEL_ID.finditer(document.text, section.heading_end, section.end))
    expected_id = "claude-opus-" + identity.version.replace(".", "-")
    if not ids or any(item[0] != expected_id for item in ids):
        raise ValueError("model_profile_id_identity_mismatch")
    intro = re.search(r"[^\r\n\s][^\r\n]*", document.text[section.heading_end:section.end])
    if intro is None:
        raise ValueError("model_profile_intro_missing")
    start, end = (section.heading_end + value for value in intro.span())
    quote = document.text[start:end]
    # The field is the paragraph immediately following the product title, not
    # arbitrary controls/navigation that happen to be inside its text section.
    paragraphs = titles[0].xpath("following-sibling::*[1][self::p]")
    if (len(paragraphs) != 1
            or " ".join(paragraphs[0].text_content().split()) != " ".join(quote.split())):
        raise ValueError("model_profile_intro_not_paragraph")
    if len(quote) > 500 or _MODEL_ID.search(quote) or re.search(r"\b(?:vs\.?|versus|compared|comparison)\b", quote, re.I):
        raise ValueError("model_profile_intro_not_positioning")
    if (re.search(r"\bClaude\s+(?!Opus\b)[A-Za-z]+", quote, re.I)
            or any(version != identity.version for version in re.findall(r"\d+(?:\.\d+)+", quote))):
        raise ValueError("model_profile_intro_other_identity")
    proposal = EvidenceProposal(identity, document.read_id, url, document.content_sha256,
                                (section.heading_start, section.heading_end), (start, end), quote)
    binding = verify_binding(document, proposal)
    if binding.status != "VERIFIED":
        raise ValueError("model_profile_intro_binding_failed")
    if source_bindings is not None:
        source_bindings["official_positioning"] = {
            "kind": "verified_version_heading", "product": identity.product, "version": identity.version,
            "url": url, "read_id": document.read_id, "source_content_sha256": document.content_sha256,
            "decoded_payload_sha256": binding.payload_sha256,
            "heading_span": [section.heading_start, section.heading_end], "heading_quote": heading,
            "source_span": [start, end], "quote": quote,
            "model_id": expected_id, "model_id_span": list(ids[0].span()),
        }
    return {"project": "Claude Opus", "version": identity.version, "official_positioning": quote}
