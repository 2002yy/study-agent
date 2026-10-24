"""AR-1C-3: readable is not the same as publication-grade.

An old answer must keep rendering the citations it has, so the legacy
quote-only binding stays valid for display. New text, however, may only enter the
published answer through a binding that names *which read* produced the sentence.
These controls pin both halves of that distinction so neither side drifts.
"""

import hashlib

from src.web.research.answer_revision import REPLACE, RevisionProposal, evaluate
from src.web.research.read_evidence import (
    PUBLICATION_GRADE_REFUSAL,
    ReadEvidence,
    verify_binding,
    verify_publication_binding,
)

NOW = "2026-10-21T00:00:00+00:00"
URL = "https://example.com/a"
EXCERPT = "版本 A 更适合旧设备，因为它在旧系统上仍受支持。"
QUOTE = "版本 A 更适合旧设备"
READ_ID = "read-7"


def _read(*, read_id: str = READ_ID) -> ReadEvidence:
    return ReadEvidence.build(url=URL, excerpt=EXCERPT, round_index=2, read_id=read_id)


def _legacy_binding() -> dict:
    return {"url": URL, "quote": QUOTE, "content_sha256": hashlib.sha256(QUOTE.encode()).hexdigest()}


def _modern_binding() -> dict:
    return {
        **_legacy_binding(),
        "read_id": READ_ID,
        "read_excerpt_sha256": hashlib.sha256(EXCERPT.encode()).hexdigest(),
    }


def _reply() -> dict:
    return {
        "schema": "steering-reply-v1",
        "reply_id": "run1:research",
        "scope": "research",
        "steering_id": "",
        "turn_id": "turn1",
        "lifecycle": "open",
        "stage": "evidence_update",
        "content_version": 3,
        "stale": False,
        "analysis_state": "ready",
        "text": "旧结论。",
        "citations": [],
        "content_state": {"round": 1, "notes": 1, "revision": "rev-1"},
        "updated_at": NOW,
    }


def _proposal(binding: dict) -> RevisionProposal:
    return RevisionProposal(
        target_reply_id="run1:research",
        target_content_version=3,
        action=REPLACE,
        reason="新读取支持更精确的表述",
        research_revision="rev-2",
        research_round=2,
        research_notes=3,
        replacement="版本 A 仍然更适合旧设备。",
        source_bindings=(binding,),
        strict=True,
    )


# -- display -----------------------------------------------------------------
def test_a_legacy_binding_is_still_readable():
    """Old answers keep their citations; we do not blank the history."""

    assert verify_binding(_legacy_binding(), (_read(),)) == ""


def test_a_legacy_binding_cannot_carry_new_published_text():
    assert verify_publication_binding(_legacy_binding(), (_read(),)) == PUBLICATION_GRADE_REFUSAL


def test_naming_the_read_without_its_excerpt_digest_is_still_not_enough():
    binding = {"url": URL, "quote": QUOTE, "read_id": READ_ID}

    assert verify_binding(binding, (_read(),)) == ""
    assert verify_publication_binding(binding, (_read(),)) == PUBLICATION_GRADE_REFUSAL


def test_a_binding_that_names_a_read_that_does_not_exist_is_refused():
    binding = {**_modern_binding(), "read_id": "read-other"}

    assert verify_binding(binding, (_read(),)) == "read_id_not_found"


# -- publication -------------------------------------------------------------
def test_a_replace_backed_only_by_a_legacy_binding_is_refused():
    decision = evaluate(_proposal(_legacy_binding()), _reply(), read_evidence=(_read(),))

    assert decision.accepted is False
    assert decision.refusal == PUBLICATION_GRADE_REFUSAL


def test_a_replace_that_names_its_read_is_accepted():
    decision = evaluate(_proposal(_modern_binding()), _reply(), read_evidence=(_read(),))

    assert decision.accepted is True
    assert decision.applied == REPLACE


def test_the_failure_direction_is_visible_not_silent():
    """The refusal names what is missing, so an operator can act on it."""

    decision = evaluate(_proposal(_legacy_binding()), _reply(), read_evidence=(_read(),))

    assert decision.refusal != "source_reads_unavailable"  # the read was there
    assert "read_id" not in decision.refusal  # a code, not a lecture
    assert decision.refusal == PUBLICATION_GRADE_REFUSAL
