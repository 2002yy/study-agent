"""Bind the Multimodal Reader's vision seam to the existing G14-c provider.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.13 boundary 2.

Production already has one gated vision path
(:mod:`src.application.attachment_vision`, ``describe_image_with_deepseek``) that
owns the provider, the model id, the audit purpose and the fail-closed error
semantics. This module only *adapts* that seam to the research-side
``VisionAdapter`` protocol:

* the independent ``attachment_vision_enabled`` setting is the gate (default off);
* the description prompt is not steered -- requirement anchoring happens
  downstream in RQ-A, so no second prompt/provider path exists;
* any failure becomes ``VisionUnavailable`` (never a raw exception).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from src.web.research.multimodal_reader import (
    VisionAdapter,
    VisionObservation,
    VisionUnavailable,
)

REASON_GATE_OFF = "vision_gate_disabled"
REASON_NOT_MATERIALIZED = "visual_image_not_materialized"
REASON_DESCRIPTION_FAILED = "vision_description_failed"
REASON_EMPTY_DESCRIPTION = "vision_empty_description"


def vision_gate_enabled() -> bool:
    """The independent operator gate (absent setting means off)."""

    try:
        from src.application.helpers import load_frontend_settings

        return bool(load_frontend_settings().get("attachment_vision_enabled"))
    except Exception:  # noqa: BLE001 - unreadable settings must not enable vision
        return False


def _default_describer() -> Callable[[Path], str]:
    from src.application.attachment_vision import describe_image_with_deepseek

    return describe_image_with_deepseek


def _vision_model_name() -> str:
    try:
        from src.application.attachment_vision import vision_model_name

        return vision_model_name()
    except Exception:  # noqa: BLE001 - the model name is audit metadata only
        return ""


def build_research_vision_adapter(
    *,
    enabled: bool | None = None,
    describer: Callable[[Path], str] | None = None,
) -> VisionAdapter:
    """A ``VisionAdapter`` bound to G14-c, or an inert one when the gate is off."""

    gate = vision_gate_enabled() if enabled is None else bool(enabled)
    if not gate:
        return VisionAdapter()

    def observe(*, image: Any, prompt: str) -> VisionObservation:
        del prompt  # requirement anchoring is downstream (RQ-A), never a prompt
        local_path = str(getattr(image, "local_path", "") or "")
        if not local_path:
            raise VisionUnavailable(REASON_NOT_MATERIALIZED)
        describe = describer or _default_describer()
        started = time.perf_counter()
        try:
            description = str(describe(Path(local_path))).strip()
        except VisionUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - normalized, never propagated raw
            raise VisionUnavailable(REASON_DESCRIPTION_FAILED) from exc
        if not description:
            raise VisionUnavailable(REASON_EMPTY_DESCRIPTION)
        return VisionObservation(
            text=description,
            confidence=0.0,
            model=_vision_model_name(),
            latency_ms=round((time.perf_counter() - started) * 1000.0, 1),
        )

    return VisionAdapter(observe)


__all__ = [
    "REASON_DESCRIPTION_FAILED",
    "REASON_EMPTY_DESCRIPTION",
    "REASON_GATE_OFF",
    "REASON_NOT_MATERIALIZED",
    "build_research_vision_adapter",
    "vision_gate_enabled",
]
