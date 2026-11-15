"""Versioned server-owned truth for factual assertions in final answers.

The current chat generator does not produce structured answer claims. This
module therefore provides a strict contract and lifecycle normalizer without
attempting to infer claims from natural-language assistant text.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from typing import Any, Iterable, Literal

from src.domain.evidence import ClaimEvidenceLinkV1

ANSWER_CLAIM_SCHEMA_VERSION = "answer-claim-snapshot-v1"

AnswerClaimKind = Literal[
    "factual",
    "synthesis",
    "premise",
    "instructional",
    "question",
    "recommendation",
    "uncertainty",
]
AnswerClaimStatus = Literal["asserted", "qualified", "withdrawn"]
AnswerClaimSource = Literal["provider_structured", "application_supplied"]
AnswerClaimSnapshotStatus = Literal[
    "unavailable",
    "supplied",
    "validated",
    "rejected",
]

_ALLOWED_KINDS: set[str] = {
    "factual",
    "synthesis",
    "premise",
    "instructional",
    "question",
    "recommendation",
    "uncertainty",
}
_ALLOWED_CLAIM_STATUSES: set[str] = {"asserted", "qualified", "withdrawn"}
_ALLOWED_SOURCES: set[str] = {"provider_structured", "application_supplied"}
_ALLOWED_SNAPSHOT_STATUSES: set[str] = {"supplied", "validated"}
_ALLOWED_SUPPORT_TYPES: set[str] = {
    "direct_support",
    "indirect_support",
    "contradicts",
}


@dataclass(frozen=True)
class AnswerClaimV1:
    id: str
    text: str
    kind: AnswerClaimKind
    status: AnswerClaimStatus
    source: AnswerClaimSource

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "status": self.status,
            "source": self.source,
        }


@dataclass(frozen=True)
class AnswerClaimSnapshotV1:
    answer_hash: str
    claims: tuple[AnswerClaimV1, ...] = ()
    claim_links: tuple[ClaimEvidenceLinkV1, ...] = ()
    producer: str = "none"
    status: AnswerClaimSnapshotStatus = "unavailable"
    reason: str = ""
    schema_version: str = ANSWER_CLAIM_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "answer_hash": self.answer_hash,
            "claims": [claim.to_dict() for claim in self.claims],
            "claim_links": [link.to_dict() for link in self.claim_links],
            "producer": self.producer,
            "status": self.status,
            "reason": self.reason,
        }


def answer_content_hash(answer: str) -> str:
    canonical = _canonical_answer(answer)
    if not canonical:
        return ""
    return sha256(canonical.encode("utf-8")).hexdigest()


def deterministic_claim_id(*, answer_hash: str, claim_text: str) -> str:
    normalized = _normalize_claim_text(claim_text)
    if not answer_hash or not normalized:
        raise ValueError("claim identity requires answer_hash and claim text")
    material = f"{answer_hash}\u0000{normalized}"
    return f"claim_{sha256(material.encode('utf-8')).hexdigest()[:24]}"


def unavailable_answer_claim_snapshot(
    *,
    answer: str = "",
    reason: str,
    producer: str = "none",
) -> AnswerClaimSnapshotV1:
    return AnswerClaimSnapshotV1(
        answer_hash=answer_content_hash(answer),
        producer=_clean_text(producer) or "none",
        status="unavailable",
        reason=_clean_text(reason) or "producer_unavailable",
    )


def rejected_answer_claim_snapshot(
    *,
    answer: str,
    reason: str,
    producer: str,
) -> AnswerClaimSnapshotV1:
    return AnswerClaimSnapshotV1(
        answer_hash=answer_content_hash(answer),
        producer=_clean_text(producer) or "unknown",
        status="rejected",
        reason=_clean_text(reason) or "invalid_snapshot",
    )


def build_answer_claim_snapshot(
    *,
    answer: str,
    claims: Iterable[AnswerClaimV1 | dict[str, Any]],
    claim_links: Iterable[ClaimEvidenceLinkV1 | dict[str, Any]] = (),
    known_evidence_ids: Iterable[str] = (),
    producer: str,
    status: Literal["supplied", "validated"] = "validated",
    trust_upstream_claim_ids: bool = False,
) -> AnswerClaimSnapshotV1:
    answer_hash = answer_content_hash(answer)
    if not answer_hash:
        raise ValueError("structured claims require a final answer")
    if status not in _ALLOWED_SNAPSHOT_STATUSES:
        raise ValueError(f"invalid answer claim snapshot status: {status}")
    normalized_producer = _clean_text(producer)
    if not normalized_producer:
        raise ValueError("structured claims require a producer")

    parsed_claims: list[AnswerClaimV1] = []
    known_claim_ids: set[str] = set()
    known_claim_texts: set[str] = set()
    for raw_claim in claims:
        claim = _parse_claim(
            raw_claim,
            answer_hash=answer_hash,
            trust_upstream_claim_ids=trust_upstream_claim_ids,
        )
        if claim.id in known_claim_ids:
            raise ValueError(f"duplicate claim id: {claim.id}")
        normalized_text = _normalize_claim_text(claim.text).casefold()
        if normalized_text in known_claim_texts:
            raise ValueError("duplicate claim text")
        known_claim_ids.add(claim.id)
        known_claim_texts.add(normalized_text)
        parsed_claims.append(claim)

    allowed_evidence_ids = {
        _clean_text(evidence_id)
        for evidence_id in known_evidence_ids
        if _clean_text(evidence_id)
    }
    parsed_links = tuple(
        _parse_claim_link(
            raw_link,
            known_claim_ids=known_claim_ids,
            known_evidence_ids=allowed_evidence_ids,
        )
        for raw_link in claim_links
    )
    link_keys: set[tuple[str, str, str]] = set()
    for link in parsed_links:
        key = (link.claim_id, link.evidence_id, link.support_type)
        if key in link_keys:
            raise ValueError("duplicate claim evidence link")
        link_keys.add(key)

    return AnswerClaimSnapshotV1(
        answer_hash=answer_hash,
        claims=tuple(parsed_claims),
        claim_links=parsed_links,
        producer=normalized_producer,
        status=status,
    )


def normalize_answer_claim_snapshot_for_turn(
    *,
    raw_snapshot: Any,
    assistant_message: str,
    turn_status: str,
    known_evidence_ids: Iterable[str] = (),
) -> AnswerClaimSnapshotV1:
    """Normalize persisted/supplied claim truth against the current Turn state."""

    if turn_status != "completed":
        return unavailable_answer_claim_snapshot(reason="turn_not_completed")

    raw = _object(raw_snapshot)
    if raw.get("schema_version") != ANSWER_CLAIM_SCHEMA_VERSION:
        return unavailable_answer_claim_snapshot(
            answer=assistant_message,
            reason="producer_unavailable",
        )

    producer = _clean_text(raw.get("producer")) or "unknown"
    raw_status = _clean_text(raw.get("status"))
    expected_hash = answer_content_hash(assistant_message)
    supplied_hash = _clean_text(raw.get("answer_hash"))

    if raw_status == "unavailable":
        return unavailable_answer_claim_snapshot(
            answer=assistant_message,
            producer=producer,
            reason=_clean_text(raw.get("reason")) or "producer_unavailable",
        )
    if raw_status == "rejected":
        return rejected_answer_claim_snapshot(
            answer=assistant_message,
            producer=producer,
            reason=_clean_text(raw.get("reason")) or "invalid_snapshot",
        )
    if raw_status not in _ALLOWED_SNAPSHOT_STATUSES:
        return rejected_answer_claim_snapshot(
            answer=assistant_message,
            producer=producer,
            reason="invalid_snapshot_status",
        )
    if not expected_hash or supplied_hash != expected_hash:
        return rejected_answer_claim_snapshot(
            answer=assistant_message,
            producer=producer,
            reason="answer_hash_mismatch",
        )

    try:
        return build_answer_claim_snapshot(
            answer=assistant_message,
            claims=_sequence(raw.get("claims")),
            claim_links=_sequence(raw.get("claim_links")),
            known_evidence_ids=known_evidence_ids,
            producer=producer,
            status=raw_status,  # type: ignore[arg-type]
            trust_upstream_claim_ids=True,
        )
    except ValueError as exc:
        return rejected_answer_claim_snapshot(
            answer=assistant_message,
            producer=producer,
            reason=f"invalid_snapshot:{_clean_text(exc)}",
        )


def _parse_claim(
    raw_claim: AnswerClaimV1 | dict[str, Any],
    *,
    answer_hash: str,
    trust_upstream_claim_ids: bool,
) -> AnswerClaimV1:
    raw = raw_claim.to_dict() if isinstance(raw_claim, AnswerClaimV1) else _object(raw_claim)
    text = _normalize_claim_text(raw.get("text"))
    if not text:
        raise ValueError("claim text is required")
    kind = _clean_text(raw.get("kind"))
    if kind not in _ALLOWED_KINDS:
        raise ValueError(f"invalid claim kind: {kind}")
    claim_status = _clean_text(raw.get("status"))
    if claim_status not in _ALLOWED_CLAIM_STATUSES:
        raise ValueError(f"invalid claim status: {claim_status}")
    source = _clean_text(raw.get("source"))
    if source not in _ALLOWED_SOURCES:
        raise ValueError(f"invalid claim source: {source}")

    generated_id = deterministic_claim_id(answer_hash=answer_hash, claim_text=text)
    supplied_id = _clean_identifier(raw.get("id"))
    if supplied_id and not trust_upstream_claim_ids and supplied_id != generated_id:
        raise ValueError("untrusted claim id does not match deterministic identity")
    claim_id = supplied_id if supplied_id and trust_upstream_claim_ids else generated_id
    return AnswerClaimV1(
        id=claim_id,
        text=text,
        kind=kind,  # type: ignore[arg-type]
        status=claim_status,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
    )


def _parse_claim_link(
    raw_link: ClaimEvidenceLinkV1 | dict[str, Any],
    *,
    known_claim_ids: set[str],
    known_evidence_ids: set[str],
) -> ClaimEvidenceLinkV1:
    raw = raw_link.to_dict() if isinstance(raw_link, ClaimEvidenceLinkV1) else _object(raw_link)
    claim_id = _clean_identifier(raw.get("claim_id"))
    evidence_id = _clean_identifier(raw.get("evidence_id"))
    support_type = _clean_text(raw.get("support_type"))
    confidence = _finite_float(raw.get("confidence"))
    if claim_id not in known_claim_ids:
        raise ValueError(f"unknown claim id: {claim_id}")
    if evidence_id not in known_evidence_ids:
        raise ValueError(f"unknown evidence id: {evidence_id}")
    if support_type not in _ALLOWED_SUPPORT_TYPES:
        raise ValueError(f"invalid support type: {support_type}")
    if confidence < 0 or confidence > 1:
        raise ValueError("claim evidence confidence must be between 0 and 1")
    return ClaimEvidenceLinkV1(
        claim_id=claim_id,
        evidence_id=evidence_id,
        support_type=support_type,
        confidence=confidence,
    )


def _canonical_answer(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def _normalize_claim_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_identifier(value: Any) -> str:
    identifier = str(value or "").strip()
    if not identifier:
        return ""
    if len(identifier) > 160 or any(character.isspace() for character in identifier):
        raise ValueError("invalid identifier")
    return identifier


def _finite_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError("confidence must be numeric") from None
    if not isfinite(parsed):
        raise ValueError("confidence must be finite")
    return parsed


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()
