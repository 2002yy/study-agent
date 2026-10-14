"""Budget-gated, non-blocking generation of the research opening.

Contract (frozen):

1. **Trigger priority** — a valid ``model_plan`` projection is used as-is (zero
   extra calls).  Only when there is no meaningful opening *and* the budget
   allows do we attempt ``model_generated``.  Otherwise the deterministic
   fallback stands and the tool progress keeps rendering.
2. **Budget permission first** — a real request is only sent after
   ``authorize`` returns True; every real attempt is counted (including
   timeouts and invalid payloads), never just successful generations.
3. **Never block research** — callers run this off the research path; the
   opening must not gate search/read.
4. **Identity/state-checked writes** — a result is written only after checking
   run identity, terminal state, and whether a ready projection or a newer
   direction already won.  ``sequence`` alone is not trusted.
5. **No late overwrite** — cancelled / failed / ended / already-projected /
   newer-direction states reject a late result.
6. **Failure never propagates** — timeout, invalid JSON, empty text and write
   contention are all swallowed here.

This module never touches the Evidence Gate, the plan envelope, the research
budget ceiling, or the answer/citation rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable

from src.web.research.research_approach import (
    APPROACH_SCHEMA,
    ORIGIN_DIRECTION_UPDATE,
    ORIGIN_FALLBACK,
    ORIGIN_MODEL_PLAN,
    STATUS_READY,
    fallback_approach,
    generate_approach_or_fallback,
    normalize_mode,
)

# A ready projection or an explicit direction update already answers "what are
# we doing"; a generated summary must never replace them.
_AUTHORITATIVE_ORIGINS = (ORIGIN_MODEL_PLAN, ORIGIN_DIRECTION_UPDATE)


@dataclass(frozen=True)
class GenerationOutcome:
    """Result of one attempt.  ``approach`` is always safe to display."""

    approach: dict[str, Any] | None
    spent: bool
    written: bool
    reason: str


def generation_needed(current: Any) -> bool:
    """Whether a generated opening is worth attempting.

    False for a valid non-fallback opening (e.g. an existing ``model_plan``
    projection), so the common path costs zero extra calls.
    """

    if not isinstance(current, dict) or current.get("schema") != APPROACH_SCHEMA:
        return True
    if current.get("status") != STATUS_READY:
        return True
    return str(current.get("origin") or "") == ORIGIN_FALLBACK


def _sequence(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def write_allowed(
    *,
    current: Any,
    candidate: Any,
    run_id: str,
    terminal: bool,
) -> bool:
    """Identity/state gate for persisting a generated opening."""

    if terminal:
        return False
    if not isinstance(candidate, dict) or candidate.get("schema") != APPROACH_SCHEMA:
        return False
    if candidate.get("status") != STATUS_READY or not candidate.get("summary"):
        return False
    if not isinstance(current, dict) or current.get("schema") != APPROACH_SCHEMA:
        return True
    # Must belong to the same run lineage; never cross runs.
    root = str(current.get("root_run_id") or "")
    if root and run_id and root != str(run_id):
        return False
    # A ready projection / direction update outranks a generated summary.
    if current.get("status") == STATUS_READY and str(
        current.get("origin") or ""
    ) in _AUTHORITATIVE_ORIGINS:
        return False
    # Ordering guard (defence in depth; not the primary gate).
    return _sequence(candidate.get("sequence")) > _sequence(current.get("sequence"))


class ApproachGenerationCoordinator:
    """Coordinates one bounded generation per authorization.

    ``authorize(run_id, operation_id) -> bool`` must be the *budget* gate; it is
    consulted before any request.  ``write(run_id, approach) -> bool`` persists a
    validated opening.  Both are injected so the policy lives with the caller and
    this class stays testable without a database.
    """

    def __init__(
        self,
        *,
        authorize: Callable[[str, str], bool],
        write: Callable[[str, dict[str, Any]], bool],
        completion: Callable[..., str] | None = None,
        timeout: float = 8.0,
        max_tokens: int = 320,
    ) -> None:
        self._authorize = authorize
        self._write = write
        self._completion = completion
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._inflight: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def attempt(
        self,
        *,
        run_id: str,
        operation_id: str,
        mode: Any,
        query: str,
        current: Any,
        is_terminal: Callable[[], bool],
        sequence: int = 1,
    ) -> GenerationOutcome:
        """One generation attempt.  Never raises."""

        if not generation_needed(current):
            return GenerationOutcome(current, spent=False, written=False, reason="not_needed")

        key = (str(run_id), str(operation_id))
        with self._lock:
            if key in self._inflight:
                # The same authorization must not consume budget twice.
                return GenerationOutcome(
                    current, spent=False, written=False, reason="duplicate_authorization"
                )
            self._inflight.add(key)
        try:
            try:
                allowed = bool(self._authorize(str(run_id), str(operation_id)))
            except Exception:
                return GenerationOutcome(
                    current, spent=False, written=False, reason="budget_error"
                )
            if not allowed:
                return GenerationOutcome(
                    current, spent=False, written=False, reason="budget_denied"
                )

            approach, spent = generate_approach_or_fallback(
                self._completion,
                mode=mode,
                query=query,
                context=None,
                root_run_id=str(run_id),
                previous=current if isinstance(current, dict) else None,
                sequence=sequence,
                timeout=self._timeout,
                max_tokens=self._max_tokens,
            )

            try:
                terminal = bool(is_terminal())
            except Exception:
                terminal = True  # fail closed on an unknown state
            if not write_allowed(
                current=current, candidate=approach, run_id=str(run_id), terminal=terminal
            ):
                return GenerationOutcome(
                    approach, spent=spent, written=False, reason="write_rejected"
                )
            try:
                written = bool(self._write(str(run_id), approach))
            except Exception:
                written = False
            return GenerationOutcome(
                approach,
                spent=spent,
                written=written,
                reason="written" if written else "write_failed",
            )
        finally:
            with self._lock:
                self._inflight.discard(key)

    def safe_fallback(
        self, *, mode: Any, run_id: str, turn_id: str = "", sequence: int = 1
    ) -> dict[str, Any]:
        return fallback_approach(
            mode=normalize_mode(mode),
            root_run_id=str(run_id),
            turn_id=turn_id,
            sequence=sequence,
        )
