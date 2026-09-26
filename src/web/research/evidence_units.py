"""Multimodal-compatible evidence units (RQ-A v1).

Frozen contract: ``docs/PROJECT_STATUS.md`` §144.4.

Text and visual evidence both reduce to a single :class:`EvidenceUnit` model so
the Claim <-> Evidence layer never needs a schema change to accept vision input
(web image / screenshot / chart / diagram / PDF figure).

Required content is declared claim-side as :class:`RequiredUnit` and may never
be inferred from already-read evidence (§144.6): evidence only reports which
units it covered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

SourceType = Literal["text", "table", "image", "chart", "screenshot", "pdf_figure"]
UnitModality = Literal["text", "visual", "any"]

SOURCE_TYPES: tuple[SourceType, ...] = (
    "text",
    "table",
    "image",
    "chart",
    "screenshot",
    "pdf_figure",
)
UNIT_MODALITIES: tuple[UnitModality, ...] = ("text", "visual", "any")

#: Source types whose evidence is carried by a picture rather than by text.
VISUAL_SOURCE_TYPES: frozenset[str] = frozenset(
    {"image", "chart", "screenshot", "pdf_figure"}
)
#: Source types whose evidence is recoverable as text (prose / tabular text).
TEXT_SOURCE_TYPES: frozenset[str] = frozenset({"text", "table"})

_MAX_UNITS = 32
_MAX_ID = 120
_MAX_TEXT = 2000
_MAX_REGION = 200
_MAX_PROVENANCE = 500
_MAX_SOURCE = 500
_MAX_OBSERVATION = 2000


def unit_satisfies_modality(*, source_type: str, modality: str) -> bool:
    """Whether an evidence unit of ``source_type`` can cover ``modality``.

    A ``visual`` requirement is deliberately *not* satisfiable by text/table
    evidence, so "the prose mentions a figure" can never masquerade as "the
    figure was read".
    """

    if modality == "any":
        return True
    if modality == "visual":
        return source_type in VISUAL_SOURCE_TYPES
    if modality == "text":
        return source_type in TEXT_SOURCE_TYPES
    raise ValueError(f"unknown unit modality: {modality}")


@dataclass(frozen=True)
class RequiredUnit:
    """A content unit a claim needs before it can be called supported."""

    unit_id: str
    description: str = ""
    modality: UnitModality = "any"

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "description": self.description,
            "modality": self.modality,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> RequiredUnit:
        data = _mapping(raw, "required unit")
        _only_keys(data, {"unit_id", "description", "modality"}, "required unit")
        return cls(
            unit_id=_id(data.get("unit_id"), "required unit id"),
            description=_optional_text(
                data.get("description"), "required unit description", _MAX_TEXT
            ),
            modality=_enum(data.get("modality", "any"), UNIT_MODALITIES, "unit modality"),
        )


@dataclass(frozen=True)
class EvidenceUnit:
    """One evidence unit recovered from a source (text or visual)."""

    unit_id: str
    source_type: SourceType = "text"
    source: str = ""
    page: int | None = None
    region: str = ""
    content: str = ""
    observation: str = ""
    supports: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    confidence: float = 0.0
    provenance: str = ""

    @property
    def is_visual(self) -> bool:
        return self.source_type in VISUAL_SOURCE_TYPES

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "source_type": self.source_type,
            "source": self.source,
            "page": self.page,
            "region": self.region,
            "content": self.content,
            "observation": self.observation,
            "supports": list(self.supports),
            "contradicts": list(self.contradicts),
            "confidence": self.confidence,
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> EvidenceUnit:
        data = _mapping(raw, "evidence unit")
        _only_keys(
            data,
            {
                "unit_id",
                "source_type",
                "source",
                "page",
                "region",
                "content",
                "observation",
                "supports",
                "contradicts",
                "confidence",
                "provenance",
            },
            "evidence unit",
        )
        return cls(
            unit_id=_id(data.get("unit_id"), "evidence unit id"),
            source_type=_enum(
                data.get("source_type", "text"), SOURCE_TYPES, "evidence unit source type"
            ),
            source=_optional_text(data.get("source"), "evidence unit source", _MAX_SOURCE),
            page=_optional_non_negative_int(data.get("page"), "evidence unit page"),
            region=_optional_text(data.get("region"), "evidence unit region", _MAX_REGION),
            content=_optional_text(data.get("content"), "evidence unit content", _MAX_TEXT),
            observation=_optional_text(
                data.get("observation"), "evidence unit observation", _MAX_OBSERVATION
            ),
            supports=_id_tuple(data.get("supports"), "evidence unit supports"),
            contradicts=_id_tuple(data.get("contradicts"), "evidence unit contradicts"),
            confidence=_number(data.get("confidence", 0.0), "evidence unit confidence"),
            provenance=_optional_text(
                data.get("provenance"), "evidence unit provenance", _MAX_PROVENANCE
            ),
        )


def parse_required_units(raw: Any) -> tuple[RequiredUnit, ...]:
    return tuple(RequiredUnit.from_dict(item) for item in _sequence(raw, "required units"))


def parse_evidence_units(raw: Any) -> tuple[EvidenceUnit, ...]:
    return tuple(EvidenceUnit.from_dict(item) for item in _sequence(raw, "evidence units"))


def _mapping(raw: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    return raw


def _only_keys(data: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        raise ValueError(f"{label} has unsupported keys: {', '.join(unexpected)}")


def _sequence(raw: Any, label: str) -> Sequence[Any]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError(f"{label} must be a list")
    if len(raw) > _MAX_UNITS:
        raise ValueError(f"{label} must contain at most {_MAX_UNITS} items")
    return raw


def _id(raw: Any, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty string")
    value = raw.strip()
    if len(value) > _MAX_ID:
        raise ValueError(f"{label} must be at most {_MAX_ID} characters")
    return value


def _optional_text(raw: Any, label: str, limit: int) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string")
    value = raw.strip()
    if len(value) > limit:
        raise ValueError(f"{label} must be at most {limit} characters")
    return value


def _enum(raw: Any, allowed: tuple[str, ...], label: str) -> Any:
    if not isinstance(raw, str) or raw not in allowed:
        raise ValueError(f"{label} must be one of: {', '.join(allowed)}")
    return raw


def _number(raw: Any, label: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{label} must be a number")
    value = float(raw)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1")
    return value


def _optional_non_negative_int(raw: Any, label: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{label} must be an integer")
    if raw < 0:
        raise ValueError(f"{label} must not be negative")
    return raw


def _id_tuple(raw: Any, label: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError(f"{label} must be a list")
    values = tuple(_id(item, label) for item in raw)
    return tuple(dict.fromkeys(values))
