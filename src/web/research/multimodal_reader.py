"""Multimodal Reader v1: visual evidence into the existing RQ chain.

Frozen contract: ``docs/PROJECT_STATUS.md`` §144.11 (plus §144.4 EvidenceUnit and
§144.5 staged escalation).

Pipeline, in order:

1. **visual candidate discovery** -- deterministic, auditable triggers only. The
   reader declares signals (``triggers``); this module never guesses "there is an
   <img> so send it to a model". A candidate without provenance is dropped.
2. **staged escalation** -- ``text -> alt/caption -> OCR/table -> vision``. Vision
   is reached only when the lower levels cannot cover the required units and the
   image is declared to carry required evidence.
3. **vision adapter** -- an injected seam, fail-closed when not configured
   (mirrors the provider/read seams elsewhere in the engine).
4. **normalize** -- one :class:`EvidenceUnit` per accepted image, always carrying
   page/region provenance.
5. **budget** -- vision calls are charged against an explicit counter; the caller
   wires it to the existing hard budget (not reset here).

It never invents a second, visual-only adequacy logic: the produced units are fed
into the same ``EvidenceUnit -> Claim assessment -> Conflict -> Coverage`` chain
as text units.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence

from src.web.research.evidence_units import EvidenceUnit, SourceType

VisualKind = Literal["image", "chart", "screenshot", "diagram", "pdf_figure", "table"]
VisualTrigger = Literal[
    "text_references_figure",
    "numbers_only_in_chart",
    "ui_state_only_in_screenshot",
    "diagram_is_evidence",
    "pdf_text_may_contradict_figure",
    "user_requested",
]
EscalationLevel = Literal["text", "alt", "ocr", "vision"]
VisualOutcomeStatus = Literal["normalized", "skipped", "unavailable"]

ESCALATION_LADDER: tuple[EscalationLevel, ...] = ("text", "alt", "ocr", "vision")

TRIGGERS: tuple[VisualTrigger, ...] = (
    "text_references_figure",
    "numbers_only_in_chart",
    "ui_state_only_in_screenshot",
    "diagram_is_evidence",
    "pdf_text_may_contradict_figure",
    "user_requested",
)

REASON_NO_TRIGGER = "no_visual_trigger"
REASON_MISSING_PROVENANCE = "missing_provenance"
REASON_LOWER_LEVELS_SUFFICIENT = "lower_levels_sufficient"
REASON_LOWER_LEVELS_INSUFFICIENT = "lower_levels_insufficient"
REASON_VISION_NOT_CONFIGURED = "vision_not_configured"
REASON_VISION_FAILED = "vision_failed"
REASON_VISION_BUDGET_EXHAUSTED = "vision_budget_exhausted"
REASON_NORMALIZED_LOWER_LEVEL = "normalized_from_lower_level"
REASON_NORMALIZED_VISION = "normalized_from_vision"

_KIND_TO_SOURCE_TYPE: Mapping[str, SourceType] = {
    "image": "image",
    "chart": "chart",
    "screenshot": "screenshot",
    "pdf_figure": "pdf_figure",
    "diagram": "image",
    "table": "table",
}


class VisionUnavailable(RuntimeError):
    """Vision could not be used (fail-closed)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class VisualBudgetExhausted(RuntimeError):
    """The explicit vision-call budget is spent."""

    def __init__(self, reason: str = REASON_VISION_BUDGET_EXHAUSTED) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VisualImage:
    """One declared visual candidate, with the signals the reader observed."""

    image_id: str
    kind: VisualKind
    source: str
    page: int | None = None
    region: str = ""
    alt: str = ""
    caption: str = ""
    nearby_text: str = ""
    ocr_text: str = ""
    triggers: tuple[VisualTrigger, ...] = ()
    carries_required_evidence: bool = False

    @property
    def provenance(self) -> str:
        anchor = f"{self.source}"
        if self.page is not None:
            anchor = f"{anchor}#page={self.page}"
        if self.region:
            anchor = f"{anchor}#region={self.region}"
        return anchor


@dataclass(frozen=True)
class VisualCandidate:
    image: VisualImage
    reason: VisualTrigger
    provenance: str

    @property
    def source_type(self) -> SourceType:
        return _KIND_TO_SOURCE_TYPE.get(self.image.kind, "image")


@dataclass(frozen=True)
class EscalationPlan:
    ladder: tuple[EscalationLevel, ...]
    stop_at: EscalationLevel
    reason: str

    @property
    def needs_vision(self) -> bool:
        return self.stop_at == "vision"


@dataclass(frozen=True)
class VisionObservation:
    text: str
    confidence: float = 0.0
    model: str = ""
    latency_ms: float = 0.0


@dataclass
class VisualReadBudget:
    """Explicit counter for vision calls (wired to the hard budget by the caller)."""

    max_vision_calls: int
    vision_calls: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_vision_calls - self.vision_calls)

    @property
    def exhausted(self) -> bool:
        return self.vision_calls >= self.max_vision_calls

    def charge(self) -> None:
        if self.exhausted:
            raise VisualBudgetExhausted()
        self.vision_calls += 1


@dataclass(frozen=True)
class VisualReadOutcome:
    image_id: str
    status: VisualOutcomeStatus
    stop_at: str
    reason: str
    unit: EvidenceUnit | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "status": self.status,
            "stop_at": self.stop_at,
            "reason": self.reason,
            "unit": self.unit.to_dict() if self.unit else None,
        }


@dataclass(frozen=True)
class VisualReadResult:
    outcomes: tuple[VisualReadOutcome, ...] = ()
    vision_calls: int = 0

    @property
    def units(self) -> tuple[EvidenceUnit, ...]:
        return tuple(item.unit for item in self.outcomes if item.unit is not None)

    @property
    def statuses(self) -> tuple[str, ...]:
        return tuple(item.status for item in self.outcomes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vision_calls": self.vision_calls,
            "outcomes": [item.to_dict() for item in self.outcomes],
        }


class VisionAdapter:
    """Injected vision seam; fail-closed when no observer is configured."""

    def __init__(
        self,
        observe: Callable[..., VisionObservation] | None = None,
    ) -> None:
        self._observe = observe

    @property
    def available(self) -> bool:
        return self._observe is not None

    def observe(self, *, image: VisualImage, prompt: str) -> VisionObservation:
        if self._observe is None:
            raise VisionUnavailable(REASON_VISION_NOT_CONFIGURED)
        return self._observe(image=image, prompt=prompt)


def visual_prompt(candidate: VisualCandidate, *, required_units: Sequence[str]) -> str:
    """A bounded, provenance-anchored prompt: describe only what the figure shows."""

    wanted = ", ".join(str(unit) for unit in required_units) or "the figure's conclusion"
    return (
        "Describe only what this figure shows and answer these points: "
        f"{wanted}. Do not infer anything the figure does not contain."
    )


def discover_visual_candidates(
    images: Sequence[VisualImage],
    *,
    user_requested: bool = False,
) -> tuple[VisualCandidate, ...]:
    """Deterministic discovery over declared signals (never guesses from markup)."""

    candidates: list[VisualCandidate] = []
    for image in images:
        triggers = list(image.triggers)
        if user_requested and "user_requested" not in triggers:
            triggers.append("user_requested")
        if not triggers:
            continue
        if not image.source:
            # An unlocated visual assertion may never enter the chain.
            continue
        candidates.append(
            VisualCandidate(
                image=image,
                reason=triggers[0],
                provenance=image.provenance,
            )
        )
    return tuple(candidates)


def plan_visual_escalation(
    candidate: VisualCandidate,
    *,
    required_units: Sequence[str] = (),
    available_units_by_level: Mapping[str, Sequence[str]] | None = None,
) -> EscalationPlan | None:
    """First ladder level that covers the requirement; ``None`` if impossible."""

    required = {str(unit) for unit in required_units}
    by_level = {
        str(level): {str(unit) for unit in units}
        for level, units in (available_units_by_level or {}).items()
    }

    for level in ("text", "alt", "ocr"):
        if required and required.issubset(by_level.get(level, set())):
            return EscalationPlan(
                ladder=ESCALATION_LADDER,
                stop_at=level,  # type: ignore[arg-type]
                reason=REASON_LOWER_LEVELS_SUFFICIENT,
            )
    if not required and by_level.get("text"):
        return EscalationPlan(
            ladder=ESCALATION_LADDER,
            stop_at="text",
            reason=REASON_LOWER_LEVELS_SUFFICIENT,
        )
    if not candidate.image.carries_required_evidence:
        return None
    return EscalationPlan(
        ladder=ESCALATION_LADDER,
        stop_at="vision",
        reason=REASON_LOWER_LEVELS_INSUFFICIENT,
    )


def to_evidence_unit(
    candidate: VisualCandidate,
    *,
    observation: VisionObservation | None = None,
    content: str = "",
) -> EvidenceUnit:
    """Normalize one accepted image into a provenance-anchored EvidenceUnit."""

    if not candidate.provenance:
        raise ValueError("visual evidence requires provenance")
    return EvidenceUnit(
        unit_id=candidate.image.image_id,
        source_type=candidate.source_type,
        source=candidate.image.source,
        page=candidate.image.page,
        region=candidate.image.region,
        content=content,
        observation=observation.text if observation else "",
        confidence=observation.confidence if observation else 0.0,
        provenance=candidate.provenance,
    )


def _lower_level_content(candidate: VisualCandidate, stop_at: str) -> str:
    if stop_at == "text":
        return candidate.image.nearby_text
    if stop_at == "alt":
        return candidate.image.alt or candidate.image.caption
    return candidate.image.ocr_text


def read_visual_candidates(
    *,
    images: Sequence[VisualImage],
    required_units: Sequence[str] = (),
    available_units_by_level: Mapping[str, Sequence[str]] | None = None,
    adapter: VisionAdapter | None = None,
    budget: VisualReadBudget | None = None,
    user_requested: bool = False,
) -> VisualReadResult:
    """Run discovery -> escalation -> (vision) -> normalize for one page/read."""

    adapter = adapter or VisionAdapter()
    budget = budget or VisualReadBudget(max_vision_calls=0)
    outcomes: list[VisualReadOutcome] = []

    for candidate in discover_visual_candidates(images, user_requested=user_requested):
        plan = plan_visual_escalation(
            candidate,
            required_units=required_units,
            available_units_by_level=available_units_by_level,
        )
        if plan is None:
            outcomes.append(
                VisualReadOutcome(
                    image_id=candidate.image.image_id,
                    status="skipped",
                    stop_at="",
                    reason=REASON_LOWER_LEVELS_INSUFFICIENT,
                )
            )
            continue
        if not plan.needs_vision:
            outcomes.append(
                VisualReadOutcome(
                    image_id=candidate.image.image_id,
                    status="normalized",
                    stop_at=plan.stop_at,
                    reason=REASON_NORMALIZED_LOWER_LEVEL,
                    unit=to_evidence_unit(
                        candidate, content=_lower_level_content(candidate, plan.stop_at)
                    ),
                )
            )
            continue
        if not adapter.available:
            outcomes.append(
                VisualReadOutcome(
                    image_id=candidate.image.image_id,
                    status="unavailable",
                    stop_at="vision",
                    reason=REASON_VISION_NOT_CONFIGURED,
                )
            )
            continue
        try:
            budget.charge()
        except VisualBudgetExhausted as exc:
            outcomes.append(
                VisualReadOutcome(
                    image_id=candidate.image.image_id,
                    status="unavailable",
                    stop_at="vision",
                    reason=exc.reason,
                )
            )
            continue
        try:
            observation = adapter.observe(
                image=candidate.image,
                prompt=visual_prompt(candidate, required_units=required_units),
            )
        except VisionUnavailable as exc:
            outcomes.append(
                VisualReadOutcome(
                    image_id=candidate.image.image_id,
                    status="unavailable",
                    stop_at="vision",
                    reason=exc.reason,
                )
            )
            continue
        except Exception:  # noqa: BLE001 - a vision failure must never break the read
            outcomes.append(
                VisualReadOutcome(
                    image_id=candidate.image.image_id,
                    status="unavailable",
                    stop_at="vision",
                    reason=REASON_VISION_FAILED,
                )
            )
            continue
        outcomes.append(
            VisualReadOutcome(
                image_id=candidate.image.image_id,
                status="normalized",
                stop_at="vision",
                reason=REASON_NORMALIZED_VISION,
                unit=to_evidence_unit(candidate, observation=observation),
            )
        )

    return VisualReadResult(outcomes=tuple(outcomes), vision_calls=budget.vision_calls)


__all__ = [
    "ESCALATION_LADDER",
    "EscalationPlan",
    "REASON_LOWER_LEVELS_INSUFFICIENT",
    "REASON_LOWER_LEVELS_SUFFICIENT",
    "REASON_MISSING_PROVENANCE",
    "REASON_NORMALIZED_LOWER_LEVEL",
    "REASON_NORMALIZED_VISION",
    "REASON_NO_TRIGGER",
    "REASON_VISION_BUDGET_EXHAUSTED",
    "REASON_VISION_FAILED",
    "REASON_VISION_NOT_CONFIGURED",
    "TRIGGERS",
    "VisionAdapter",
    "VisionObservation",
    "VisionUnavailable",
    "VisualBudgetExhausted",
    "VisualCandidate",
    "VisualImage",
    "VisualKind",
    "VisualReadBudget",
    "VisualReadOutcome",
    "VisualReadResult",
    "VisualTrigger",
    "discover_visual_candidates",
    "plan_visual_escalation",
    "read_visual_candidates",
    "to_evidence_unit",
    "visual_prompt",
]
