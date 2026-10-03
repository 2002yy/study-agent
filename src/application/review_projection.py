"""§169-B ReviewProjection: the time dimension, derived and read-only.

Answers one question per confirmed understanding: is it due for review? It is a **pure
projection** over existing durable truth - ``UnderstandingEvidence`` timestamps plus the
latest validation result - and deliberately persists nothing. Per the §169-A contract the
due state is a derived view, not a second source of truth, so this module has no writer and
no state of its own.

Scope (frozen in §169-A):

* only a confirmed understanding (a ``pass`` result) is reviewable;
* due is a pure time condition from the last validation, with a fixed interval;
* a failure never demotes existing understanding, so only passes are considered here;
* misconceptions, next steps and the current turn's gap do not trigger review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

# Fixed interval to start; spacing algorithms are explicitly out of scope for now.
REVIEW_INTERVAL = timedelta(days=7)

PASS_RESULT = "pass"

REASON_DUE = "elapsed_since_last_validation"
REASON_NOT_DUE = "within_review_interval"


@dataclass(frozen=True)
class ReviewProjection:
    """One confirmed understanding's review state. Derived; never persisted."""

    claim_revision_id: str
    last_validated_at: str
    next_review_at: str
    due: bool
    reason: str


def _parse(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def project_review(
    pairs: Iterable[tuple[object, object]],
    *,
    now: datetime | None = None,
    interval: timedelta = REVIEW_INTERVAL,
) -> tuple[ReviewProjection, ...]:
    """Derive the review state for each confirmed understanding. Never raises.

    ``pairs`` are ``(UnderstandingEvidence, UnderstandingClaimResult)`` tuples as read
    from the durable truth repository. Only the latest ``pass`` per claim revision counts;
    a later failing attempt does not erase the fact that it was once validated.
    """

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    latest_pass: dict[str, datetime] = {}
    for evidence, result in pairs:
        if str(getattr(result, "result", "")) != PASS_RESULT:
            continue
        revision_id = str(getattr(result, "claim_revision_id", "") or "")
        verified = _parse(str(getattr(evidence, "verified_at", "") or ""))
        if not revision_id or verified is None:
            continue
        current = latest_pass.get(revision_id)
        if current is None or verified > current:
            latest_pass[revision_id] = verified

    projections: list[ReviewProjection] = []
    for revision_id, verified in sorted(latest_pass.items()):
        due_at = verified + interval
        is_due = moment >= due_at
        projections.append(
            ReviewProjection(
                claim_revision_id=revision_id,
                last_validated_at=verified.isoformat(),
                next_review_at=due_at.isoformat(),
                due=is_due,
                reason=REASON_DUE if is_due else REASON_NOT_DUE,
            )
        )
    return tuple(projections)


def due_reviews(
    projections: Sequence[ReviewProjection],
) -> tuple[ReviewProjection, ...]:
    """The subset that is due - what a resume/review decision would act on."""
    return tuple(item for item in projections if item.due)
