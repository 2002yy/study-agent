"""Verify proposed spans against one reader-owned document and version section.

No LLM verdict, URL seed or relevance score can create a verified binding. This
initial capability binds headings only; other anchor kinds remain UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit

from src.web.research.identity import ResearchIdentity, identities_in_text


@dataclass(frozen=True)
class VersionSection:
    heading_start: int
    heading_end: int
    end: int


@dataclass(frozen=True)
class ReadDocument:
    read_id: str
    source_url: str
    payload_sha256: str
    text: str
    content_sha256: str
    sections: tuple[VersionSection, ...]


class _VisibleDocument(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.length = 0
        self.sections: list[list[int]] = []
        self.hidden = 0
        self.heading = False

    def append(self, value: str) -> None:
        self.chunks.append(value)
        self.length += len(value)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        # Inline badges must not join a version token ("5.5Latest"). Preserve
        # boundaries only within headings; other source quotes stay unchanged.
        if self.heading and tag not in {"h1", "h2", "h3", "h4", "h5", "h6", "br"}:
            self.append(" ")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.append("\n")
            if self.sections:
                self.sections[-1][2] = self.length
            self.sections.append([self.length, self.length, self.length])
            self.heading = True
        elif tag == "br":
            self.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
            return
        if self.hidden:
            return
        if self.heading and tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.append(" ")
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading:
            self.sections[-1][1] = self.length
            self.heading = False
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.append(data)


def document_from_read(read_id: str, source_url: str, payload: bytes) -> ReadDocument:
    """Reader-side adapter for successfully fetched, decompressed UTF-8 HTML.

    Must be called at the trusted read boundary, never on model-supplied HTML.
    Sections stop at every next heading, conservatively including subheadings.
    """
    parser = _VisibleDocument()
    parser.feed(payload.decode("utf-8", errors="strict"))
    parser.close()
    if parser.sections:
        parser.sections[-1][2] = parser.length
    text = "".join(parser.chunks)
    return ReadDocument(read_id, source_url, hashlib.sha256(payload).hexdigest(), text,
                        hashlib.sha256(text.encode()).hexdigest(),
                        tuple(VersionSection(*section) for section in parser.sections))


@dataclass(frozen=True)
class EvidenceProposal:
    identity: ResearchIdentity
    read_id: str
    source_url: str
    content_sha256: str
    heading_span: tuple[int, int]
    evidence_span: tuple[int, int]
    quote: str


@dataclass(frozen=True)
class VersionEvidenceBinding:
    status: str
    reason: str
    proposal: EvidenceProposal
    payload_sha256: str = ""


def verify_binding(document: ReadDocument, proposal: EvidenceProposal) -> VersionEvidenceBinding:
    def unknown(reason: str) -> VersionEvidenceBinding:
        return VersionEvidenceBinding("UNKNOWN", reason, proposal)

    url = urlsplit(document.source_url)
    if not document.read_id or url.scheme != "https" or not url.hostname or url.username or url.password:
        return unknown("invalid_read_identity")
    digest = hashlib.sha256(document.text.encode()).hexdigest()
    if (proposal.read_id != document.read_id or proposal.source_url != document.source_url
            or proposal.content_sha256 != document.content_sha256 or document.content_sha256 != digest):
        return unknown("read_binding_mismatch")
    section = next((item for item in document.sections
                    if (item.heading_start, item.heading_end) == proposal.heading_span), None)
    if section is None:
        return unknown("heading_not_reader_derived")
    anchor = document.text[section.heading_start:section.heading_end]
    identities = identities_in_text(anchor)
    if not identities or any(identity != proposal.identity for identity in identities):
        return unknown("heading_identity_missing_or_ambiguous")
    start, end = proposal.evidence_span
    if not section.heading_end <= start < end <= section.end:
        return unknown("evidence_outside_version_section")
    quote = document.text[start:end]
    if not quote.strip() or quote != proposal.quote:
        return unknown("quote_mismatch")
    if any(identity != proposal.identity for identity in identities_in_text(quote)):
        return unknown("quote_contains_other_identity")
    return VersionEvidenceBinding("VERIFIED", "exact_heading_and_span", proposal, document.payload_sha256)
