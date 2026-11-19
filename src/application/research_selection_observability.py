"""Bounded selection-window diagnostics, without selector or reader authority."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.selection_authority import SelectionAuthorityDiagnostics


SELECTION_RECORD_LIMIT = 40


def _fingerprint(values: Iterable[Any]) -> str:
    """Return the order-independent fingerprint used by historical diagnostics."""

    items = sorted(str(item) for item in values)
    return hashlib.sha1("|".join(items).encode("utf-8")).hexdigest()[:16]


def record_selection_authority(
    metrics: dict[str, Any],
    *,
    claim_id: str,
    candidates: Sequence[CandidatePoolItem],
    excluded_candidate_ids: frozenset[str],
    window_limit: int,
    wave_index: int,
    orchestration_model_call: int,
    diagnostics: SelectionAuthorityDiagnostics,
    now_ms: Callable[[], Any] | None = None,
) -> None:
    """Append the existing diagnostic projection without issuing model calls.

    Preserve both independent timing samples, historical field order, and the
    most recent 40 records, including records left by an earlier wave.
    """

    records = metrics.get("selection_authority")
    if not isinstance(records, list):
        records = []
    previous = next(
        (
            entry
            for entry in reversed(records)
            if isinstance(entry, Mapping)
            and str(entry.get("claim_id") or "") == claim_id
        ),
        None,
    )
    input_ids = sorted(item.id for item in candidates)
    input_urls = sorted(item.canonical_url for item in candidates)
    excluded_ids = sorted(str(item) for item in excluded_candidate_ids)
    fingerprint = _fingerprint([*input_ids, *input_urls])
    previous_ids = (
        set(previous.get("input_ids") or []) if isinstance(previous, Mapping) else set()
    )
    previous_fingerprint = (
        str(previous.get("input_fingerprint") or "")
        if isinstance(previous, Mapping)
        else ""
    )
    previous_excluded = (
        str(previous.get("excluded_fingerprint") or "")
        if isinstance(previous, Mapping)
        else ""
    )
    records.append(
        {
            "wave_index": wave_index,
            "claim_id": claim_id,
            "window_limit": window_limit,
            "orchestration_model_call": orchestration_model_call,
            "input_fingerprint": fingerprint,
            "previous_input_fingerprint": previous_fingerprint,
            "input_changed": fingerprint != previous_fingerprint,
            "input_ids": input_ids,
            "new_candidate_count": len(set(input_ids) - previous_ids),
            "removed_candidate_count": len(previous_ids - set(input_ids)),
            "excluded_fingerprint": _fingerprint(excluded_ids),
            "assessment_state_changed": _fingerprint(excluded_ids)
            != previous_excluded,
            "t_started_ms": round(float(now_ms()), 1) if now_ms else None,
            "t_ended_ms": round(float(now_ms()), 1) if now_ms else None,
            **diagnostics.to_dict(),
        }
    )
    metrics["selection_authority"] = records[-SELECTION_RECORD_LIMIT:]
