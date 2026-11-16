from __future__ import annotations

import pytest

from src.domain.answer_claims import (
    ANSWER_CLAIM_SCHEMA_VERSION,
    answer_content_hash,
    build_answer_claim_snapshot,
    deterministic_claim_id,
    normalize_answer_claim_snapshot_for_turn,
)


ANSWER = "FastAPI uses Python type hints to validate request data."


def _claim(text: str = ANSWER) -> dict:
    return {
        "text": text,
        "kind": "factual",
        "status": "asserted",
        "source": "application_supplied",
    }


def test_answer_hash_and_claim_id_are_deterministic_and_not_position_based():
    answer_hash = answer_content_hash(ANSWER)
    first = deterministic_claim_id(answer_hash=answer_hash, claim_text=ANSWER)
    second = deterministic_claim_id(
        answer_hash=answer_hash,
        claim_text="  FastAPI uses Python type hints to validate request data.  ",
    )

    assert answer_hash == answer_content_hash(f"{ANSWER}\n")
    assert first == second
    assert first.startswith("claim_")


def test_build_snapshot_generates_claim_identity_and_validates_known_evidence():
    answer_hash = answer_content_hash(ANSWER)
    claim_id = deterministic_claim_id(answer_hash=answer_hash, claim_text=ANSWER)

    snapshot = build_answer_claim_snapshot(
        answer=ANSWER,
        claims=[_claim()],
        claim_links=[
            {
                "claim_id": claim_id,
                "evidence_id": "chunk-1",
                "support_type": "direct_support",
                "confidence": 0.95,
            }
        ],
        known_evidence_ids=["chunk-1"],
        producer="unit-test",
    )

    assert snapshot.schema_version == ANSWER_CLAIM_SCHEMA_VERSION
    assert snapshot.answer_hash == answer_hash
    assert snapshot.claims[0].id == claim_id
    assert snapshot.claim_links[0].evidence_id == "chunk-1"
    assert snapshot.status == "validated"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("kind", "opinion", "invalid claim kind"),
        ("status", "guessed", "invalid claim status"),
        ("source", "frontend_inferred", "invalid claim source"),
    ],
)
def test_invalid_claim_enums_are_rejected(field: str, value: str, message: str):
    claim = _claim()
    claim[field] = value

    with pytest.raises(ValueError, match=message):
        build_answer_claim_snapshot(
            answer=ANSWER,
            claims=[claim],
            producer="unit-test",
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("inf"), "not-a-number"])
def test_invalid_link_confidence_is_rejected(confidence):
    claim_id = deterministic_claim_id(
        answer_hash=answer_content_hash(ANSWER),
        claim_text=ANSWER,
    )

    with pytest.raises(ValueError, match="confidence"):
        build_answer_claim_snapshot(
            answer=ANSWER,
            claims=[_claim()],
            claim_links=[
                {
                    "claim_id": claim_id,
                    "evidence_id": "chunk-1",
                    "support_type": "direct_support",
                    "confidence": confidence,
                }
            ],
            known_evidence_ids=["chunk-1"],
            producer="unit-test",
        )


def test_unknown_evidence_and_unknown_claim_links_are_rejected():
    claim_id = deterministic_claim_id(
        answer_hash=answer_content_hash(ANSWER),
        claim_text=ANSWER,
    )

    with pytest.raises(ValueError, match="unknown evidence id"):
        build_answer_claim_snapshot(
            answer=ANSWER,
            claims=[_claim()],
            claim_links=[
                {
                    "claim_id": claim_id,
                    "evidence_id": "missing",
                    "support_type": "direct_support",
                    "confidence": 0.9,
                }
            ],
            known_evidence_ids=["chunk-1"],
            producer="unit-test",
        )

    with pytest.raises(ValueError, match="unknown claim id"):
        build_answer_claim_snapshot(
            answer=ANSWER,
            claims=[_claim()],
            claim_links=[
                {
                    "claim_id": "claim_missing",
                    "evidence_id": "chunk-1",
                    "support_type": "direct_support",
                    "confidence": 0.9,
                }
            ],
            known_evidence_ids=["chunk-1"],
            producer="unit-test",
        )


def test_completed_turn_rejects_snapshot_for_a_different_answer():
    snapshot = build_answer_claim_snapshot(
        answer=ANSWER,
        claims=[_claim()],
        producer="unit-test",
    ).to_dict()

    normalized = normalize_answer_claim_snapshot_for_turn(
        raw_snapshot=snapshot,
        assistant_message="A different final answer.",
        turn_status="completed",
    )

    assert normalized.status == "rejected"
    assert normalized.reason == "answer_hash_mismatch"
    assert normalized.claims == ()
    assert normalized.claim_links == ()


def test_non_completed_turn_always_invalidates_supplied_claim_truth():
    snapshot = build_answer_claim_snapshot(
        answer=ANSWER,
        claims=[_claim()],
        producer="unit-test",
    ).to_dict()

    for status in ("pending", "streaming", "interrupted", "failed", "abandoned"):
        normalized = normalize_answer_claim_snapshot_for_turn(
            raw_snapshot=snapshot,
            assistant_message=ANSWER,
            turn_status=status,
        )
        assert normalized.status == "unavailable"
        assert normalized.answer_hash == ""
        assert normalized.reason == "turn_not_completed"
        assert normalized.claims == ()


def test_completed_turn_without_structured_producer_is_explicitly_unavailable():
    normalized = normalize_answer_claim_snapshot_for_turn(
        raw_snapshot={},
        assistant_message=ANSWER,
        turn_status="completed",
    )

    assert normalized.status == "unavailable"
    assert normalized.answer_hash == answer_content_hash(ANSWER)
    assert normalized.reason == "producer_unavailable"
    assert normalized.claims == ()
    assert normalized.claim_links == ()


def test_trusted_upstream_claim_id_is_preserved_only_in_trusted_mode():
    claim = {**_claim(), "id": "provider_claim_42", "source": "provider_structured"}

    with pytest.raises(ValueError, match="untrusted claim id"):
        build_answer_claim_snapshot(
            answer=ANSWER,
            claims=[claim],
            producer="provider-sidecar",
        )

    snapshot = build_answer_claim_snapshot(
        answer=ANSWER,
        claims=[claim],
        producer="provider-sidecar",
        status="supplied",
        trust_upstream_claim_ids=True,
    )

    assert snapshot.claims[0].id == "provider_claim_42"
    assert snapshot.status == "supplied"

def test_a_blocked_turn_keeps_its_recorded_rejection_reason():
    """A blocked research turn must stay diagnosable.

    Collapsing every rejection to "turn_not_completed" hides whether the answer
    was rejected for a missing quote, a fabricated one, or a provider failure.
    """

    normalized = normalize_answer_claim_snapshot_for_turn(
        raw_snapshot={
            "schema_version": "answer-claim-snapshot-v1",
            "status": "unavailable",
            "reason": "batch_1_of_6:unverified_source_quote",
            "producer": "answer_claim_binding",
        },
        assistant_message=ANSWER,
        turn_status="failed",
    )

    assert normalized.status == "unavailable"
    assert normalized.reason == "batch_1_of_6:unverified_source_quote"
