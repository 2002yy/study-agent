"""Declarative visual-metadata projection for the read payload.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.13 boundary 1.

The read payload does not carry images today, so the multimodal integration needs
one explicit channel. This module reads **only** a declared
``visual_metadata`` list and normalizes it into
:class:`~src.web.research.multimodal_reader.VisualImage` values.

It never inspects markup and never guesses: an entry without a trigger, without a
source anchor (provenance) or with an unknown kind is dropped. Discovery then
applies the same rules again, so this projection can only ever narrow.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.web.research.multimodal_reader import TRIGGERS, VisualImage

VISUAL_METADATA_KEY = "visual_metadata"
MAX_VISUAL_METADATA_ENTRIES = 8

ALLOWED_VISUAL_KINDS: frozenset[str] = frozenset(
    {"image", "chart", "screenshot", "diagram", "pdf_figure", "table"}
)


def project_visual_metadata(read_payload: Any) -> tuple[VisualImage, ...]:
    """Normalize the declared visual-metadata channel; drop anything unqualified."""

    if not isinstance(read_payload, Mapping):
        return ()
    raw = read_payload.get(VISUAL_METADATA_KEY)
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        return ()

    images: list[VisualImage] = []
    for entry in list(raw)[:MAX_VISUAL_METADATA_ENTRIES]:
        if not isinstance(entry, Mapping):
            continue
        image = _to_image(entry)
        if image is not None:
            images.append(image)
    return tuple(images)


def _to_image(entry: Mapping[str, Any]) -> VisualImage | None:
    kind = str(entry.get("kind") or "").strip().lower()
    if kind not in ALLOWED_VISUAL_KINDS:
        return None
    source = str(entry.get("source") or "").strip()
    if not source:
        return None
    declared = entry.get("triggers")
    if isinstance(declared, (str, bytes)) or not isinstance(declared, Sequence):
        return None
    triggers = tuple(str(item) for item in declared if str(item) in TRIGGERS)
    if not triggers:
        return None
    image_id = str(entry.get("image_id") or "").strip()
    if not image_id:
        return None
    return VisualImage(
        image_id=image_id,
        kind=kind,  # type: ignore[arg-type]
        source=source,
        page=_optional_int(entry.get("page")),
        region=str(entry.get("region") or "").strip(),
        alt=str(entry.get("alt") or "").strip(),
        caption=str(entry.get("caption") or "").strip(),
        nearby_text=str(entry.get("nearby_text") or "").strip(),
        ocr_text=str(entry.get("ocr_text") or "").strip(),
        triggers=triggers,  # type: ignore[arg-type]
        carries_required_evidence=bool(entry.get("carries_required_evidence")),
    )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


__all__ = [
    "ALLOWED_VISUAL_KINDS",
    "MAX_VISUAL_METADATA_ENTRIES",
    "VISUAL_METADATA_KEY",
    "project_visual_metadata",
]
