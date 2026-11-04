"""Bounded source-bound patch preparation; browser acceptance owns publication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from src.interactive_restore import RestoreRequest, TurnLike, locate_restore_source


class PatchConflict(ValueError):
    pass


@dataclass(frozen=True)
class TextEdit:
    old: str
    new: str


@dataclass(frozen=True)
class PatchCandidate:
    component_id: str
    base_revision: int
    revision: int
    base_sha256: str
    html: str

    @property
    def sha256(self) -> str:
        return source_hash(self.html)


def source_hash(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def prepare_patch(
    turns: Iterable[TurnLike],
    request: RestoreRequest,
    expected_sha256: str,
    edits: list[TextEdit],
) -> PatchCandidate:
    """Locate saved source and atomically apply unique, non-overlapping edits.

    All edit anchors refer to the original source. No mutation or persistence
    occurs until every identity, hash and conflict check has passed.
    """
    if (
        RestoreRequest.from_payload({"id": request.id, "revision": request.revision})
        != request
    ):
        raise PatchConflict("invalid target identity")
    outcome = locate_restore_source(turns, request)
    if not outcome.restorable or outcome.html is None or outcome.next_revision is None:
        raise PatchConflict(f"source unavailable: {outcome.status}")
    original = outcome.html
    if source_hash(original) != expected_sha256:
        raise PatchConflict("source hash mismatch")
    if not edits or len(edits) > 32:
        raise PatchConflict("require between 1 and 32 edits")
    spans = []
    for edit in edits:
        if (
            not isinstance(edit, TextEdit)
            or not isinstance(edit.old, str)
            or not isinstance(edit.new, str)
        ):
            raise PatchConflict("edits must contain old/new text")
        if edit.old == original:
            raise PatchConflict("whole-document replacement is not a bounded patch")
        start = original.find(edit.old) if edit.old else -1
        if start < 0 or original.find(edit.old, start + 1) >= 0:
            raise PatchConflict("edit anchor must match exactly once")
        spans.append((start, start + len(edit.old), edit.new))
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise PatchConflict("overlapping edits")
    result = original
    for start, end, replacement in reversed(spans):
        result = result[:start] + replacement + result[end:]
    if not result.strip() or len(result) > 60000:
        raise PatchConflict("candidate exceeds document bounds")
    return PatchCandidate(
        request.id, request.revision, outcome.next_revision, expected_sha256, result
    )
