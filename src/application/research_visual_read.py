"""Production entry for visual evidence: metadata -> fetch -> vision -> units.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.13 (integration boundaries) and
§144.12 (the v1 pipeline it composes).

The read site can call :func:`read_visual_evidence` after a successful read. The
function is **production-capable but default-inert**:

* with no declared ``visual_metadata`` it returns immediately;
* with ``RESEARCH_VISION_MAX_CALLS`` unset (default 0) or the G14-c gate off, it
  performs no fetch and no vision call;
* a failed fetch or a failed description degrades to a bounded ``unavailable``
  outcome and never breaks the read.

Every accepted image becomes a provenance-anchored ``EvidenceUnit`` that feeds
the existing RQ chain, and every attempt is recorded as a research-side
external-call audit entry.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from src.application.research_vision_adapter import build_research_vision_adapter
from src.web.research.contracts import ResearchState
from src.web.research.multimodal_reader import (
    VisionAdapter,
    VisualImage,
    VisualReadOutcome,
    VisualReadResult,
    discover_visual_candidates,
    plan_visual_escalation,
    read_visual_candidates,
)
from src.web.research.visual_image_fetch import ImageFetchError, materialize_image
from src.web.research.visual_metadata import project_visual_metadata
from src.web.research.visual_read_budget import (
    record_visual_audit,
    visual_audit_record,
    visual_read_budget,
)


def read_visual_evidence(
    *,
    read_payload: Any,
    required_units: Sequence[str] = (),
    available_units_by_level: Mapping[str, Sequence[str]] | None = None,
    state: ResearchState | None = None,
    context: MutableMapping[str, Any] | None = None,
    fetcher: Any = None,
    destination_dir: Path | None = None,
    adapter: VisionAdapter | None = None,
    user_requested: bool = False,
) -> VisualReadResult:
    """Read declared visual evidence for one successful read (fail-closed)."""

    images = project_visual_metadata(read_payload)
    if not images:
        return VisualReadResult()

    budget = visual_read_budget(state)
    active_adapter = (
        adapter if adapter is not None else build_research_vision_adapter()
    )

    prepared, fetch_failures = _materialize_for_vision(
        images,
        required_units=required_units,
        available_units_by_level=available_units_by_level,
        budget=budget,
        fetcher=fetcher,
        destination_dir=destination_dir,
        user_requested=user_requested,
    )

    result = read_visual_candidates(
        images=prepared,
        required_units=required_units,
        available_units_by_level=available_units_by_level,
        adapter=active_adapter,
        budget=budget,
        user_requested=user_requested,
    )

    if fetch_failures:
        # An image that never materialized must not consume a vision-call slot
        # nor reach the adapter: report it directly, in declared order.
        reader_outcomes = {item.image_id: item for item in result.outcomes}
        outcomes: list[VisualReadOutcome] = []
        for image in images:
            if image.image_id in fetch_failures:
                outcomes.append(
                    VisualReadOutcome(
                        image_id=image.image_id,
                        status="unavailable",
                        stop_at="vision",
                        reason=fetch_failures[image.image_id],
                    )
                )
            elif image.image_id in reader_outcomes:
                outcomes.append(reader_outcomes[image.image_id])
        result = VisualReadResult(outcomes=tuple(outcomes), vision_calls=result.vision_calls)

    if context is not None:
        _record_audit(context, result)

    return result


def _materialize_for_vision(
    images: tuple[VisualImage, ...],
    *,
    required_units: Sequence[str],
    available_units_by_level: Mapping[str, Sequence[str]] | None,
    budget: Any,
    fetcher: Any,
    destination_dir: Path | None,
    user_requested: bool,
) -> tuple[list[VisualImage], dict[str, str]]:
    """Fetch only the images whose escalation actually reaches vision."""

    prepared: list[VisualImage] = []
    fetch_errors: dict[str, str] = {}
    for image in images:
        candidates = discover_visual_candidates([image], user_requested=user_requested)
        if not candidates:
            continue
        plan = plan_visual_escalation(
            candidates[0],
            required_units=required_units,
            available_units_by_level=available_units_by_level,
        )
        needs_vision = (
            plan is not None
            and plan.needs_vision
            and budget.remaining > 0
        )
        if not needs_vision:
            prepared.append(image)
            continue
        if fetcher is None or destination_dir is None:
            prepared.append(image)
            continue
        try:
            fetched = materialize_image(
                image.source, fetcher=fetcher, destination_dir=destination_dir
            )
        except ImageFetchError as exc:
            fetch_errors[image.image_id] = exc.reason
            continue
        prepared.append(replace(image, local_path=str(fetched.path)))
    return prepared, fetch_errors


def _record_audit(context: MutableMapping[str, Any], result: VisualReadResult) -> None:
    for outcome in result.outcomes:
        unit = outcome.unit
        record_visual_audit(
            context,
            visual_audit_record(
                image_id=outcome.image_id,
                evidence_id=unit.unit_id if unit is not None else "",
                status=outcome.status,
                reason=outcome.reason,
            ),
        )


__all__ = ["read_visual_evidence"]
