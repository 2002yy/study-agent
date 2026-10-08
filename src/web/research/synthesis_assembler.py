"""§148 Synthesis assembler: projection (control plane) + read-only evidence.

Frozen contract: ``docs/PROJECT_STATUS.md`` §148.

The writer only decides *how to express* things. The **fact boundary and citation
coverage are enforced by code**:

* every factual assertion must carry at least one ``evidence_ref``;
* every ref must be one the projection authorised (no new facts);
* a claim with an unresolved conflict may not be expressed as a settled fact, and
  ``not_evaluated`` may not be expressed as a confident claim (structural stance
  check -- the writer declares a stance, the validator rejects illegal ones);
* the projection's ``limitations`` may not be silently dropped.

Violations are hard failures, never warnings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from src.web.research.contracts import ResearchState
from src.web.research.research_brief_projection import (
    ResearchBriefProjection,
)

SynthesisStance = Literal["asserted", "limited", "contested", "not_evaluated"]

REASON_UNCOVERED_ASSERTION = "assertion_without_evidence_ref"
REASON_UNAUTHORIZED_REF = "unauthorized_evidence_ref"
REASON_STANCE_VIOLATION = "stance_not_allowed"
REASON_LIMITATIONS_DROPPED = "limitations_dropped"
REASON_CITATION_MISSING = "citation_missing"
REASON_VISUAL_LOCATOR_MISSING = "visual_locator_missing"

_VISUAL_MODALITIES = frozenset({"image", "chart", "screenshot", "pdf_figure"})


class SynthesisContractViolation(ValueError):
    """The draft broke the §148 contract (fail closed, never a warning)."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}:{detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class EvidencePayloadUnit:
    """One unit of an evidence payload.

    An evidence object may carry several units (text and visual, several pages), and they are
    all part of the same evidence identity. They are kept as units rather than collapsed into a
    single set of singular fields, because collapsing loses whichever unit came last.
    """

    unit_id: str
    source: str = ""
    modality: str = "unknown"
    provenance: str = ""
    content: str = ""
    observation: str = ""
    page: int | None = None
    region: str = ""

    @property
    def is_visual(self) -> bool:
        return self.modality in _VISUAL_MODALITIES

    def unit_text(self) -> str:
        return self.observation or self.content

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "source": self.source,
            "modality": self.modality,
            "provenance": self.provenance,
            "page": self.page,
            "region": self.region,
        }


@dataclass(frozen=True)
class EvidencePayload:
    """Read-only data plane: what the referenced evidence actually contains.

    ``units`` holds every unit of this evidence, in the authoritative order. The singular fields
    remain for backwards-compatible construction and behave as one implicit unit, so existing
    callers that never dealt in units keep working unchanged.
    """

    evidence_id: str
    source: str = ""
    locator: str = ""
    modality: str = "unknown"
    provenance: str = ""
    content: str = ""
    observation: str = ""
    page: int | None = None
    region: str = ""
    units: tuple[EvidencePayloadUnit, ...] = ()

    @property
    def effective_units(self) -> tuple[EvidencePayloadUnit, ...]:
        """Every unit, treating the singular fields as one implicit unit when none are set."""

        if self.units:
            return self.units
        return (
            EvidencePayloadUnit(
                unit_id=self.evidence_id,
                source=self.source,
                modality=self.modality,
                provenance=self.provenance,
                content=self.content,
                observation=self.observation,
                page=self.page,
                region=self.region,
            ),
        )

    @property
    def is_visual(self) -> bool:
        return any(unit.is_visual for unit in self.effective_units)

    def citation_label(self) -> str:
        """text -> source + locator; visual -> every source + page + region.

        A multi-visual evidence keeps every locator: collapsing to the last unit would make the
        citation point at one chart while claiming to support the whole evidence.
        """

        units = self.effective_units
        visuals = [unit for unit in units if unit.is_visual]
        if visuals:
            parts: list[str] = []
            for unit in visuals:
                label = [unit.source or unit.provenance or self.source or self.evidence_id]
                if unit.page is not None:
                    label.append(f"p.{unit.page}")
                if unit.region:
                    label.append(unit.region)
                parts.append(" ".join(part for part in label if part))
            return "; ".join(parts)
        anchor = self.locator or self.provenance
        return f"{self.source or self.evidence_id} ({anchor})" if anchor else (
            self.source or self.evidence_id
        )

    def text(self) -> str:
        """Every non-empty unit in order. No unit disappears because a sibling shares the id."""

        parts = [unit.unit_text() for unit in self.effective_units]
        return " ".join(part for part in parts if part)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "locator": self.locator,
            "modality": self.modality,
            "provenance": self.provenance,
            "page": self.page,
            "region": self.region,
            "units": [unit.to_dict() for unit in self.units],
        }


@dataclass(frozen=True)
class SynthesisCitation:
    evidence_id: str
    label: str
    modality: str
    provenance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "label": self.label,
            "modality": self.modality,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class SynthesisAssertion:
    assertion_id: str
    claim_id: str
    statement: str
    evidence_refs: tuple[str, ...] = ()
    stance: SynthesisStance = "asserted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "claim_id": self.claim_id,
            "statement": self.statement,
            "evidence_refs": list(self.evidence_refs),
            "stance": self.stance,
        }


@dataclass(frozen=True)
class SynthesisSection:
    section_id: str
    text: str
    assertions: tuple[SynthesisAssertion, ...] = ()
    citations: tuple[SynthesisCitation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "text": self.text,
            "assertions": [item.to_dict() for item in self.assertions],
            "citations": [item.to_dict() for item in self.citations],
        }


@dataclass(frozen=True)
class SynthesisCoverageReport:
    factual_assertions: int = 0
    covered_assertions: int = 0
    uncovered_assertions: int = 0
    unauthorized_refs: tuple[str, ...] = ()

    @property
    def fully_covered(self) -> bool:
        return self.uncovered_assertions == 0 and not self.unauthorized_refs

    def to_dict(self) -> dict[str, Any]:
        return {
            "factual_assertions": self.factual_assertions,
            "covered_assertions": self.covered_assertions,
            "uncovered_assertions": self.uncovered_assertions,
            "unauthorized_refs": list(self.unauthorized_refs),
            "fully_covered": self.fully_covered,
        }


@dataclass(frozen=True)
class SynthesisDraft:
    sections: tuple[SynthesisSection, ...] = ()
    limitations: tuple[str, ...] = ()
    coverage_report: SynthesisCoverageReport = field(default_factory=SynthesisCoverageReport)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [item.to_dict() for item in self.sections],
            "limitations": list(self.limitations),
            "coverage_report": self.coverage_report.to_dict(),
        }


def allowed_stances(
    *,
    semantic_adequacy: str,
    confidence: str,
    conflict_status: str,
) -> frozenset[str]:
    """Deterministic stance table: how a claim may be expressed at all."""

    if semantic_adequacy == "not_evaluated":
        return frozenset({"not_evaluated"})
    if conflict_status == "unresolved_conflict":
        return frozenset({"contested"})
    if confidence == "low":
        return frozenset({"limited", "contested"})
    if confidence == "medium":
        return frozenset({"limited", "contested"})
    return frozenset({"asserted", "limited"})


def collect_evidence_payloads(state: ResearchState) -> tuple[EvidencePayload, ...]:
    """The read-only data plane, derived from the persisted evidence only."""

    payloads: list[EvidencePayload] = []
    for evidence in state.evidence:
        # Exactly one payload per evidence identity, carrying every unit. Emitting one payload
        # per unit under the same evidence_id made any evidence_id-keyed map keep only the last
        # unit and silently drop the rest.
        units = tuple(
            EvidencePayloadUnit(
                unit_id=unit.unit_id,
                source=unit.source,
                modality=unit.source_type,
                provenance=unit.provenance,
                content=unit.content,
                observation=unit.observation,
                page=unit.page,
                region=unit.region,
            )
            for unit in evidence.units
        )
        payloads.append(
            EvidencePayload(
                evidence_id=evidence.evidence_id,
                # The singular fields mirror the first unit so existing consumers that read
                # source/provenance/modality keep working; `units` carries all of them.
                source=units[0].source if units else "",
                locator=evidence.locator,
                modality=units[0].modality if units else "unknown",
                provenance=units[0].provenance if units else "",
                page=units[0].page if units else None,
                region=units[0].region if units else "",
                units=units,
            )
        )
    return tuple(payloads)


def extractive_writer(
    projection: ResearchBriefProjection,
    payloads: Mapping[str, EvidencePayload],
) -> tuple[SynthesisSection, ...]:
    """Deterministic, model-free default writer: one section per claim.

    It only restates the claim with the evidence the projection authorised, so it
    is a safe baseline for tests and for operators who do not inject a writer.
    """

    stances = _stance_lookup(projection)
    sections: list[SynthesisSection] = []
    for claim in projection.claims:
        refs = tuple(ref for ref in claim.evidence_refs if ref in payloads)
        allowed = stances.get(claim.claim_id, frozenset({"limited"}))
        stance = _pick_stance(allowed)
        citations = tuple(
            SynthesisCitation(
                evidence_id=ref,
                label=payloads[ref].citation_label(),
                modality=payloads[ref].modality,
                provenance=payloads[ref].provenance,
            )
            for ref in refs
        )
        body = " ".join(
            part for part in (payloads[ref].text() for ref in refs) if part
        )
        sections.append(
            SynthesisSection(
                section_id=f"claim:{claim.claim_id}",
                text=body,
                assertions=(
                    SynthesisAssertion(
                        assertion_id=f"a:{claim.claim_id}",
                        claim_id=claim.claim_id,
                        statement=claim.statement,
                        evidence_refs=refs,
                        stance=stance,
                    ),
                ),
                citations=citations,
            )
        )
    return tuple(sections)


def assemble_synthesis_draft(
    *,
    projection: ResearchBriefProjection,
    payloads: Iterable[EvidencePayload],
    writer: Callable[
        [ResearchBriefProjection, Mapping[str, EvidencePayload]],
        Sequence[SynthesisSection],
    ]
    | None = None,
) -> SynthesisDraft:
    """Assemble and validate; a contract violation raises, never degrades."""

    by_id = {payload.evidence_id: payload for payload in payloads}
    sections = tuple((writer or extractive_writer)(projection, by_id))
    draft = SynthesisDraft(
        sections=sections,
        limitations=projection.limitations,
        coverage_report=SynthesisCoverageReport(),
    )
    report = validate_synthesis_draft(draft, projection=projection, payloads=by_id)
    return SynthesisDraft(
        sections=draft.sections,
        limitations=draft.limitations,
        coverage_report=report,
    )


def validate_synthesis_draft(
    draft: SynthesisDraft,
    *,
    projection: ResearchBriefProjection,
    payloads: Mapping[str, EvidencePayload] | None = None,
) -> SynthesisCoverageReport:
    """Mechanical checks: facts, refs, stances, limitations. Raises on violation."""

    authorized_by_claim = {
        claim.claim_id: set(claim.evidence_refs) for claim in projection.claims
    }
    stances = _stance_lookup(projection)

    factual = 0
    covered = 0
    uncovered = 0
    unauthorized: list[str] = []

    for section in draft.sections:
        cited = {citation.evidence_id: citation for citation in section.citations}
        for assertion in section.assertions:
            factual += 1
            if not assertion.evidence_refs:
                uncovered += 1
                raise SynthesisContractViolation(
                    REASON_UNCOVERED_ASSERTION, assertion.assertion_id
                )
            covered += 1
            for ref in assertion.evidence_refs:
                if ref not in authorized_by_claim.get(assertion.claim_id, set()):
                    unauthorized.append(ref)
                    raise SynthesisContractViolation(REASON_UNAUTHORIZED_REF, ref)
            allowed = stances.get(assertion.claim_id)
            if allowed is not None and assertion.stance not in allowed:
                raise SynthesisContractViolation(
                    REASON_STANCE_VIOLATION,
                    f"{assertion.assertion_id}:{assertion.stance}",
                )
            if payloads is not None:
                for ref in assertion.evidence_refs:
                    citation = cited.get(ref)
                    if citation is None or ref not in payloads:
                        raise SynthesisContractViolation(
                            REASON_CITATION_MISSING, f"{assertion.assertion_id}:{ref}"
                        )
                    payload = payloads[ref]
                    # Every visual unit needs its own locator in the citation; checking only
                    # the singular fields would let a second chart go unlocated.
                    for unit in payload.effective_units:
                        if not unit.is_visual:
                            continue
                        if (
                            unit.page is None
                            or not unit.region
                            or f"p.{unit.page}" not in citation.label
                            or unit.region not in citation.label
                        ):
                            raise SynthesisContractViolation(
                                REASON_VISUAL_LOCATOR_MISSING,
                                f"{assertion.assertion_id}:{ref}",
                            )

    for limitation in projection.limitations:
        if limitation not in draft.limitations:
            raise SynthesisContractViolation(REASON_LIMITATIONS_DROPPED, limitation)

    return SynthesisCoverageReport(
        factual_assertions=factual,
        covered_assertions=covered,
        uncovered_assertions=uncovered,
        unauthorized_refs=tuple(unauthorized),
    )


def _stance_lookup(
    projection: ResearchBriefProjection,
) -> dict[str, frozenset[str]]:
    conflicts = {
        item.claim_id: item.conflict_status for item in projection.contradictions
    }
    lookup: dict[str, frozenset[str]] = {}
    for claim in projection.claims:
        lookup[claim.claim_id] = allowed_stances(
            semantic_adequacy=claim.semantic_adequacy,
            confidence=claim.confidence,
            conflict_status=conflicts.get(claim.claim_id, "none"),
        )
    return lookup


def _pick_stance(allowed: frozenset[str]) -> SynthesisStance:
    for candidate in ("asserted", "limited", "contested", "not_evaluated"):
        if candidate in allowed:
            return candidate  # type: ignore[return-value]
    return "limited"


__all__ = [
    "EvidencePayload",
    "REASON_CITATION_MISSING",
    "REASON_LIMITATIONS_DROPPED",
    "REASON_STANCE_VIOLATION",
    "REASON_UNAUTHORIZED_REF",
    "REASON_UNCOVERED_ASSERTION",
    "REASON_VISUAL_LOCATOR_MISSING",
    "SynthesisAssertion",
    "SynthesisCitation",
    "SynthesisContractViolation",
    "SynthesisCoverageReport",
    "SynthesisDraft",
    "SynthesisSection",
    "SynthesisStance",
    "allowed_stances",
    "assemble_synthesis_draft",
    "collect_evidence_payloads",
    "extractive_writer",
    "validate_synthesis_draft",
]
