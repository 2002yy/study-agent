"""Learning State-1 L1: read-only authority projection.

Classifies learning-state assertions by **authority** — where a statement came
from and whether it is allowed to count as mastery evidence. This module is a
pure read projection:

* it never writes durable truth;
* it never mutates legacy state;
* it is never an input to evaluation or planning.

Five authority classes (frozen, ``docs/LEARNING_STATE_1_CONTRACT.md`` §2.1):

``user_goal``
    A learning goal the user explicitly asked for.
``user_self_report``
    The user says they know / understand / have mastered something.
``system_inferred``
    The teaching system, model or heuristic inferred it.
``verified``
    Backed by a formal durable Understanding record. The **only** authority
    that may count as mastery evidence, and only within its own scope.
``legacy_unverified``
    A historic record with no traceable authority. Conservative fallback; the
    five-class model must never be forced onto one of the first four.

The projection deliberately does **not** decide that a Claim is masterable just
because a field is called ``confirmed_points``. Field names, text similarity,
model confidence and heuristic ``passed`` are not authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

AUTHORITY_USER_GOAL = "user_goal"
AUTHORITY_USER_SELF_REPORT = "user_self_report"
AUTHORITY_SYSTEM_INFERRED = "system_inferred"
AUTHORITY_VERIFIED = "verified"
AUTHORITY_LEGACY_UNVERIFIED = "legacy_unverified"

AUTHORITIES: tuple[str, ...] = (
    AUTHORITY_USER_GOAL,
    AUTHORITY_USER_SELF_REPORT,
    AUTHORITY_SYSTEM_INFERRED,
    AUTHORITY_VERIFIED,
    AUTHORITY_LEGACY_UNVERIFIED,
)

KIND_GOAL = "goal"
KIND_CLAIM = "claim"
KIND_GAP = "gap"
KIND_NEXT_STEP = "next_step"
KIND_UNDERSTANDING = "understanding"

KINDS: tuple[str, ...] = (
    KIND_GOAL, KIND_CLAIM, KIND_GAP, KIND_NEXT_STEP, KIND_UNDERSTANDING,
)

# Only a formal durable Understanding record grants mastery evidence. Everything
# else is context, material or a prompt for further work.
_MASTERY_AUTHORITIES = frozenset({AUTHORITY_VERIFIED})

# The durable understanding_status vocabulary (learner_model / learning_resume).
_UNDERSTANDING_CONFIRMED = "confirmed"

# Source labels are provenance strings, never secret or generated identifiers.
SOURCE_LEGACY_CONFIRMED_POINTS = "legacy_learning_state.confirmed_points"
SOURCE_DURABLE_UNDERSTANDING = "durable.understanding"


def is_mastery_authority(authority: str) -> bool:
    """True only for the one authority allowed to be mastery evidence."""
    return authority in _MASTERY_AUTHORITIES


@dataclass(frozen=True)
class LearningAuthorityItem:
    """One classified learning assertion. Read-only."""

    kind: str
    authority: str
    text: str = ""
    source: str = ""
    source_id: str = ""
    authority_reason: str = ""

    @property
    def is_mastery_evidence(self) -> bool:
        return is_mastery_authority(self.authority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "authority": self.authority,
            "text": self.text,
            "source": self.source,
            "source_id": self.source_id,
            "authority_reason": self.authority_reason,
            "is_mastery_evidence": self.is_mastery_evidence,
        }


def classify_legacy_confirmed_points(
    points: Iterable[object],
    *,
    source: str = SOURCE_LEGACY_CONFIRMED_POINTS,
) -> tuple[LearningAuthorityItem, ...]:
    """Classify legacy ``confirmed_points`` conservatively.

    A legacy point carries no traceable per-point authority (the legacy field
    conflates user self-report, heuristic conclusions and teaching progression),
    so every point is ``legacy_unverified`` unless a caller supplies a stronger
    authority. Callers must not invent a ``source_id``: it is left empty when
    none is genuinely known.
    """
    items: list[LearningAuthorityItem] = []
    for raw in points or ():
        text = str(raw or "").strip()
        if not text:
            continue
        items.append(
            LearningAuthorityItem(
                kind=KIND_CLAIM,
                authority=AUTHORITY_LEGACY_UNVERIFIED,
                text=text,
                source=source,
                source_id="",
                authority_reason="legacy record without a traceable authority",
            )
        )
    return tuple(items)


def classify_durable_understanding_status(
    status: str,
    *,
    text: str = "",
    source_id: str = "",
    source: str = SOURCE_DURABLE_UNDERSTANDING,
) -> LearningAuthorityItem:
    """Classify a durable Claim understanding status.

    ``confirmed`` is the only status backed by a formal durable Understanding
    record, so it is the only one projected as ``verified``. ``partial`` /
    ``attempted`` / ``proposed`` are system assessments, not mastery.

    This function does **not** re-derive Claim lineage. The caller is
    responsible for resolving a status the existing durable authority (e.g.
    ``LearningResumeService`` / ``LearnerModelService``) already recognises,
    including the established rule that an older revision's validation may be
    projected along the Claim lineage.
    """
    normalized = str(status or "").strip().lower()
    if normalized == _UNDERSTANDING_CONFIRMED:
        return LearningAuthorityItem(
            kind=KIND_UNDERSTANDING,
            authority=AUTHORITY_VERIFIED,
            text=text,
            source=source,
            source_id=source_id,
            authority_reason="durable understanding confirmed (pass)",
        )
    return LearningAuthorityItem(
        kind=KIND_UNDERSTANDING,
        authority=AUTHORITY_SYSTEM_INFERRED,
        text=text,
        source=source,
        source_id=source_id,
        authority_reason=f"durable understanding status '{normalized or 'none'}' is not mastery",
    )


def classify_expected_concept(text: str) -> LearningAuthorityItem:
    """Classify a curriculum target.

    An ``expected_concept`` is an **evaluation target**, not a result. Even an
    explicit, well-formed curriculum target is never ``verified``.
    """
    return LearningAuthorityItem(
        kind=KIND_GOAL,
        authority=AUTHORITY_USER_GOAL,
        text=str(text or "").strip(),
        source="explicit_expected_concept",
        source_id="",
        authority_reason="evaluation target, not a mastery result",
    )


def summarize_authorities(
    items: Sequence[LearningAuthorityItem],
) -> dict[str, Any]:
    """Compact read-only summary for telemetry / navigation labels."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item.authority] = counts.get(item.authority, 0) + 1
    return {
        "total": len(items),
        "by_authority": counts,
        "mastery_evidence_count": sum(
            1 for item in items if item.is_mastery_evidence
        ),
    }


def project_legacy_confirmed_points_authority(
    learning_state: object,
) -> tuple[LearningAuthorityItem, ...]:
    """Read-only authority projection of a legacy ``LearningState``.

    Never returns ``verified``: the legacy turn state cannot, by itself, carry
    a formal durable Understanding record.
    """
    points = getattr(learning_state, "confirmed_points", ()) or ()
    return classify_legacy_confirmed_points(points)


# --- consumer-rule helpers -------------------------------------------------

def resolve_expected_concepts(
    payload: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Resolve ``expected_concepts`` for evaluation **without** legacy fallback.

    Learning State-1 §2.4: ``expected_concepts`` may only come from an explicit
    curriculum target in ``payload['expected_concepts']``. It must never fall
    back to legacy ``confirmed_points``. A malformed value is ignored
    conservatively rather than split character-by-character.
    """
    if not isinstance(payload, Mapping):
        return ()
    raw = payload.get("expected_concepts")
    if isinstance(raw, str):
        value = raw.strip()
        return (value,) if value else ()
    if isinstance(raw, (list, tuple)):
        return tuple(
            item.strip()
            for item in (str(value or "") for value in raw)
            if item.strip()
        )
    return ()
