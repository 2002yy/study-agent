"""A4 shadow: measure what qualification would add, and what it would let wrong.

The approved A4 scope is offline: the official path keeps publishing under the
literal rule, while a shadow path asks what the A1 -> A3 chain would have done and
records it. This module implements the shadow ledger and its two gate metrics.

Two numbers matter, and they pull against each other:

* **correct increment** - claims the literal rule refused, that the qualification
  path would publish, and that an independent annotation agrees are supported;
* **false release** - claims the qualification path would publish while the
  annotation says the passage does not support them (causation read into a
  co-occurrence, a reversed direction, a wrong number, a denial).

False release is a safety gate, not a tradeable quantity: no amount of increment
makes a report safe while it is above zero. And when an annotation is missing,
the report says ``unmeasured`` rather than assuming the best - an unlabelled
release is an unknown risk, not a success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from src.web.research.claim_span_provenance import ClaimSpanVerification
from src.web.research.support_qualification import (
    ClaimJudgement,
    ClaimSupportDecision,
    decide_claim_support,
)


@dataclass(frozen=True)
class ShadowCase:
    """One claim as it appears in a real answer, plus what the literal rule did."""

    claim_id: str
    claim_text: str
    candidates: tuple[ClaimSpanVerification, ...]
    judgements: tuple[ClaimJudgement, ...]
    #: What the current publication path decided. The shadow never changes it.
    literal_bound: bool = False


@dataclass(frozen=True)
class Annotation:
    """An independent judgement about whether the passage supports the claim.

    This is the measuring stick, not a model output: it must come from a person
    or a frozen answer key, and it is deliberately separate from the verdict the
    shadow path consumed.
    """

    claim_id: str
    support_is_correct: bool
    note: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "Annotation":
        return cls(
            claim_id=str(raw.get("claim_id") or ""),
            support_is_correct=bool(raw.get("support_is_correct")),
            note=str(raw.get("note") or ""),
        )


@dataclass(frozen=True)
class ShadowRecord:
    claim_id: str
    claim_text: str
    literal_bound: bool
    decision: ClaimSupportDecision
    annotation: Annotation | None = None

    @property
    def would_publish(self) -> bool:
        return self.decision.publishable

    @property
    def is_increment(self) -> bool:
        """Refused today, publishable in shadow, and independently correct."""

        return (
            self.would_publish
            and not self.literal_bound
            and self.annotation is not None
            and self.annotation.support_is_correct
        )

    @property
    def is_false_release(self) -> bool:
        """Publishable in shadow while the independent annotation disagrees."""

        return (
            self.would_publish
            and self.annotation is not None
            and not self.annotation.support_is_correct
        )


@dataclass(frozen=True)
class ShadowReport:
    records: tuple[ShadowRecord, ...]
    literal_refused: int = 0
    shadow_qualified: int = 0
    correct_increment: int = 0
    false_release: int = 0
    unannotated: int = 0
    measured: bool = False
    safe: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def false_release_rate(self) -> float | None:
        if not self.measured or not self.shadow_qualified:
            return None
        return round(self.false_release / self.shadow_qualified, 3)


def run_shadow(
    cases: Iterable[ShadowCase],
    annotations: Iterable[Annotation | Mapping[str, object]] = (),
) -> ShadowReport:
    """Run the shadow path and score it against independent annotations."""

    by_claim: dict[str, Annotation] = {}
    for annotation in annotations:
        normalized = (
            annotation
            if isinstance(annotation, Annotation)
            else Annotation.from_mapping(annotation)
        )
        by_claim[normalized.claim_id] = normalized
    records: list[ShadowRecord] = []
    for case in cases:
        decision = decide_claim_support(
            case.claim_id, candidates=case.candidates, judgements=case.judgements
        )
        records.append(
            ShadowRecord(
                claim_id=case.claim_id,
                claim_text=case.claim_text,
                literal_bound=case.literal_bound,
                decision=decision,
                annotation=by_claim.get(case.claim_id),
            )
        )

    literal_refused = sum(1 for record in records if not record.literal_bound)
    shadow_qualified = sum(1 for record in records if record.would_publish)
    correct_increment = sum(1 for record in records if record.is_increment)
    false_release = sum(1 for record in records if record.is_false_release)
    unannotated = sum(
        1
        for record in records
        if record.would_publish and record.annotation is None
    )
    notes: list[str] = []
    if unannotated:
        notes.append(
            f"{unannotated} shadow release(s) have no independent annotation: "
            "the correctness of the increment is unmeasured"
        )
    if false_release:
        notes.append(
            f"{false_release} release(s) contradict the independent annotation: "
            "this is a safety failure, not a coverage trade"
        )
    return ShadowReport(
        records=tuple(records),
        literal_refused=literal_refused,
        shadow_qualified=shadow_qualified,
        correct_increment=correct_increment,
        false_release=false_release,
        unannotated=unannotated,
        # A report is only measured when every release it would make has been
        # independently labelled; otherwise the missing labels could hide a
        # false release.
        measured=unannotated == 0,
        safe=unannotated == 0 and false_release == 0,
        notes=tuple(notes),
    )


def as_rows(report: ShadowReport) -> tuple[dict[str, object], ...]:
    """One flat row per claim, for a shadow ledger or a human review table."""

    rows: list[dict[str, object]] = []
    for record in report.records:
        rows.append(
            {
                "claim_id": record.claim_id,
                "claim_text": record.claim_text,
                "literal_bound": record.literal_bound,
                "shadow_verdict": record.decision.verdict,
                "shadow_publishable": record.would_publish,
                "qualified_evidence": [q.evidence_id for q in record.decision.qualified],
                "refused": [item.get("reason", "") for item in record.decision.refused],
                "annotated": record.annotation is not None,
                "annotation_correct": (
                    None
                    if record.annotation is None
                    else record.annotation.support_is_correct
                ),
                "increment": record.is_increment,
                "false_release": record.is_false_release,
            }
        )
    return tuple(rows)
