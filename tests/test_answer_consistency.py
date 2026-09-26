"""§40c evidence-consistency gate: mechanical checks over the ledger."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.application.answer_claim_binder import AnswerClaimBindingRow
from src.application.answer_consistency import (
    CONSISTENCY_GATE_ENV,
    check_answer_consistency,
    consistency_gate_enabled,
)

SUPPORT_ID = "evidence_supports"
LEAD_ID = "evidence_lead"
CLAIM_ID = "research_claim_1"


@dataclass
class _Claim:
    id: str
    kind: str = "factual"
    status: str = "asserted"


@dataclass
class _Link:
    claim_id: str
    evidence_id: str
    support_type: str = "direct_support"


def _row(evidence_id: str, relation: str) -> AnswerClaimBindingRow:
    return AnswerClaimBindingRow(
        evidence_id=evidence_id,
        claim_id=CLAIM_ID,
        relation=relation,
        strength="strong" if relation == "supports" else "weak",
    )


def test_gate_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONSISTENCY_GATE_ENV, raising=False)
    assert consistency_gate_enabled() is False
    monkeypatch.setenv(CONSISTENCY_GATE_ENV, "on")
    assert consistency_gate_enabled() is True
    monkeypatch.setenv(CONSISTENCY_GATE_ENV, "no")
    assert consistency_gate_enabled() is False


def test_clean_answer_passes_with_supports_ledger() -> None:
    report = check_answer_consistency(
        candidate="该版本已正式发布 [web-1]。",
        claims=[_Claim(id="claim_answer_1")],
        links=[_Link(claim_id="claim_answer_1", evidence_id=SUPPORT_ID)],
        rows=[_row(SUPPORT_ID, "supports"), _row(LEAD_ID, "lead")],
    )
    assert report.ok is True
    assert report.checked_claims == 1
    assert report.checked_links == 1


def test_denial_text_conflicts_with_supports_ledger() -> None:
    report = check_answer_consistency(
        candidate="本轮没有任何证据可以支持该结论。",
        claims=[_Claim(id="claim_answer_1")],
        links=[_Link(claim_id="claim_answer_1", evidence_id=SUPPORT_ID)],
        rows=[_row(SUPPORT_ID, "supports")],
    )
    assert report.ok is False
    assert report.evidence_state_conflicts == ("没有任何证据",)
    assert report.codes() == ("evidence_state_conflict",)


def test_denial_text_is_fine_without_a_supports_row() -> None:
    report = check_answer_consistency(
        candidate="本轮没有任何证据可以支持该结论。",
        claims=[],
        links=[],
        rows=[_row(LEAD_ID, "lead")],
    )
    assert report.ok is True


def test_unknown_ids_and_unbound_claims_are_counted() -> None:
    report = check_answer_consistency(
        candidate="text",
        claims=[_Claim(id="claim_answer_1"), _Claim(id="claim_answer_2")],
        links=[
            _Link(claim_id="claim_answer_1", evidence_id="evidence_unknown"),
            _Link(claim_id="claim_answer_ghost", evidence_id=SUPPORT_ID),
        ],
        rows=[_row(SUPPORT_ID, "supports")],
    )
    assert report.unknown_evidence_ids == ("evidence_unknown",)
    assert report.unknown_claim_ids == ("claim_answer_ghost",)
    assert report.unbound_substantive_claims == ("claim_answer_2",)
    # claim_answer_1 only points at an unknown id, so it also has no positive
    # support direction against the ledger.
    assert report.direction_violations == ("claim_answer_1",)
    assert report.codes() == (
        "unknown_evidence_ids",
        "unknown_claim_ids",
        "unbound_substantive_claims",
        "direction_violations",
    )


def test_direction_requires_a_supports_row() -> None:
    report = check_answer_consistency(
        candidate="text",
        claims=[_Claim(id="claim_answer_1")],
        links=[_Link(claim_id="claim_answer_1", evidence_id=LEAD_ID)],
        rows=[_row(LEAD_ID, "lead")],
    )
    assert report.ok is False
    assert report.direction_violations == ("claim_answer_1",)
