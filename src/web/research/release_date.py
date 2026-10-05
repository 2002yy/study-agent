"""Deterministic labelled dates, bound to one reader-derived version section."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from src.web.research.evidence_binding import EvidenceProposal, ReadDocument, VersionEvidenceBinding, verify_binding
from src.web.research.identity import ResearchIdentity


_MONTHS = {name: index for index, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_LABELLED = re.compile(
    r"(?m)^[ \t]*release[ \t]+date:[ \t]*(?P<value>[^\r\n]+)", re.I)


def normalize_release_date(value: str) -> str | None:
    """Accept ISO dates or an explicit English month/day/year; never infer locale."""
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value.strip())
    english = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})", value.strip())
    try:
        if iso:
            return date(int(iso[1]), int(iso[2]), int(iso[3])).isoformat()
        if english:
            month = _MONTHS.get(english[1].casefold()[:3])
            if month and english[1].casefold() in {
                "jan", "january", "feb", "february", "mar", "march", "apr", "april", "may",
                "jun", "june", "jul", "july", "aug", "august", "sep", "september", "oct", "october",
                "nov", "november", "dec", "december",
            }:
                return date(int(english[3]), month, int(english[2])).isoformat()
    except ValueError:
        pass
    return None


@dataclass(frozen=True)
class BoundReleaseDate:
    value: str
    binding: VersionEvidenceBinding


def extract_release_date(document: ReadDocument, identity: ResearchIdentity) -> BoundReleaseDate | None:
    dates: list[BoundReleaseDate] = []
    for section in document.sections:
        for match in _LABELLED.finditer(document.text, section.heading_end, section.end):
            value = normalize_release_date(match["value"])
            if value is None:
                continue
            proposal = EvidenceProposal(identity, document.read_id, document.source_url, document.content_sha256,
                                        (section.heading_start, section.heading_end), match.span(), match[0])
            binding = verify_binding(document, proposal)
            if binding.status == "VERIFIED":
                dates.append(BoundReleaseDate(value, binding))
    # Ambiguity is not resolved by choosing the first date or asking a model.
    return dates[0] if len(dates) == 1 else None
