"""B1: only a passed publication may turn a source into a visible citation.

Selection is not citation. These controls pin the projection in
``ChatTurn``/``build_evidence_snapshot`` against the design contract in
``docs/EVIDENCE_CITATION_CONTRACT.md``; they use the persisted turn state and
never call a model.
"""

from __future__ import annotations

from typing import Any

from src.domain.answer_claims import answer_content_hash
from src.domain.answer_validation import sha256_text
from src.domain.evidence import MIN_VERIFIED_CITATION_CONFIDENCE
from src.domain.runtime_entities import ChatTurn
from src.web.research.evidence_gate import STRONG_EVIDENCE_THRESHOLD

ANSWER = "该版本已正式发布。"
EVIDENCE_ID = "tool_read_1"


def _audit(
    *,
    binding: str = "passed",
    candidate: str | None = None,
    learner: str | None = None,
) -> dict[str, Any]:
    candidate_hash = candidate if candidate is not None else sha256_text(ANSWER)
    learner_hash = learner if learner is not None else candidate_hash
    return {
        "schema_version": "answer-validation-audit-v1",
        "candidate_answer_sha256": candidate_hash,
        "learner_answer_sha256": learner_hash,
        "phases": {
            "answer_generation": {
                "attempted": True,
                "model_calls": 1,
                "attempts": 1,
                "outcome": "completed",
                "error_type": "",
            },
            "answer_claim_binding": {
                "attempted": True,
                "model_calls": 1,
                "attempts": 1,
                "outcome": binding,
                "error_type": "" if binding == "passed" else "ineligible_evidence_support",
            },
        },
    }


def _claim_snapshot(
    *,
    status: str = "validated",
    answer_hash: str | None = None,
    evidence_id: str = EVIDENCE_ID,
    confidence: float = 0.7,
) -> dict[str, Any]:
    claim_id = "claim_abc"
    return {
        "schema_version": "answer-claim-snapshot-v1",
        "answer_hash": answer_hash if answer_hash is not None else answer_content_hash(ANSWER),
        "claims": [
            {
                "id": claim_id,
                "text": ANSWER,
                "kind": "factual",
                "status": "asserted",
                "source": "provider_structured",
            }
        ],
        "claim_links": [
            {
                "claim_id": claim_id,
                "evidence_id": evidence_id,
                "support_type": "direct_support",
                "confidence": confidence,
            }
        ],
        "producer": "answer_claim_binder_v3",
        "status": status,
        "reason": "",
    }


def _turn(
    *,
    audit: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    refs: list[dict[str, Any]] | None = None,
    message: str = ANSWER,
) -> ChatTurn:
    rag: dict[str, Any] = {
        "research_evidence_refs": refs
        if refs is not None
        else [
            {
                "evidence_id": EVIDENCE_ID,
                "title": "Official release notes",
                "url": "https://official.example/release",
                "source_cluster_id": "official.example",
            }
        ],
    }
    if audit is not None:
        rag["answer_validation_audit"] = audit
    if snapshot is not None:
        rag["answer_claim_snapshot"] = snapshot
    return ChatTurn(
        id="turn-citation",
        thread_id="thread-citation",
        status="completed",
        assistant_message=message,
        rag_snapshot=rag,
    )


def _citation_status(turn: ChatTurn, evidence_id: str = EVIDENCE_ID) -> str:
    for ref in turn.evidence_snapshot["refs"]:
        if ref["id"] == evidence_id:
            return str(ref["citation_status"])
    raise AssertionError(f"missing ref: {evidence_id}")


def test_a_passed_publication_cites_the_linked_source() -> None:
    turn = _turn(audit=_audit(), snapshot=_claim_snapshot())

    assert turn.rag_snapshot["citation_links"] == [
        {
            "claim_id": "claim_abc",
            "evidence_id": EVIDENCE_ID,
            "support_type": "direct_support",
            "confidence": 0.7,
        }
    ]
    assert _citation_status(turn) == "cited"


def test_a_rejected_binding_has_no_verified_citation() -> None:
    turn = _turn(audit=_audit(binding="rejected"), snapshot=_claim_snapshot(status="rejected"))

    assert turn.rag_snapshot["citation_links"] == []
    assert _citation_status(turn) == "unverified"


def test_a_replaced_answer_removes_the_citations() -> None:
    """The consistency gate can replace the answer after binding passed."""

    # The turn kept the blocked copy; the candidate hash and the snapshot still
    # belong to the answer that was never published.
    turn = _turn(
        audit=_audit(candidate=sha256_text(ANSWER)),
        snapshot=_claim_snapshot(),
        message="本次尚未取得能逐事实支持所问内容的记录。",
    )

    assert turn.rag_snapshot["citation_links"] == []
    assert _citation_status(turn) != "cited"


def test_a_selected_source_without_a_claim_link_is_not_a_citation() -> None:
    turn = _turn(
        audit=_audit(),
        snapshot=_claim_snapshot(),
        refs=[
            {
                "evidence_id": EVIDENCE_ID,
                "title": "Official release notes",
                "url": "https://official.example/release",
                "source_cluster_id": "official.example",
            },
            {
                "evidence_id": "web_source_2",
                "title": "Another page",
                "url": "https://other.example/page",
                "source_cluster_id": "other.example",
            },
        ],
    )

    assert _citation_status(turn, "web_source_2") != "cited"


def test_a_link_to_an_unknown_source_is_dropped() -> None:
    turn = _turn(
        audit=_audit(),
        snapshot=_claim_snapshot(evidence_id="missing_source"),
    )

    assert turn.rag_snapshot["citation_links"] == []
    assert turn.rag_snapshot["answer_claim_snapshot"]["status"] == "rejected"


def test_the_citation_bar_matches_the_binder_support_bar() -> None:
    assert MIN_VERIFIED_CITATION_CONFIDENCE == STRONG_EVIDENCE_THRESHOLD


def test_a_legacy_turn_gains_the_projection_without_migration() -> None:
    """Turns persisted before this field still get a status when re-read."""

    turn = _turn(audit=_audit(), snapshot=_claim_snapshot())
    # Simulate the stored v1 snapshot from before citation_status existed.
    turn.rag_snapshot.pop("evidence_snapshot", None)
    for ref in turn.rag_snapshot.get("refs", []) or []:
        ref.pop("citation_status", None)

    legacy = ChatTurn(
        id=turn.id,
        thread_id=turn.thread_id,
        status="completed",
        assistant_message=ANSWER,
        rag_snapshot={
            **turn.rag_snapshot,
            "answer_claim_snapshot": _claim_snapshot(),
            "answer_validation_audit": _audit(),
        },
    )

    assert _citation_status(legacy) == "cited"
