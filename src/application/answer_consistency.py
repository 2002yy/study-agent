"""§40c mechanical evidence-consistency gate for gate-pass answers.

The binder already enforces citation existence, factual-segment binding and
positive support direction at parse time (unknown ids, unbound factual
segments and non-support rows all reject). This module adds the check the
structured path cannot see: **the generated text must not contradict the
evidence ledger** (e.g. claiming "there is no validated evidence" while the
ledger contains a supports row), and re-counts the other three classes
defensively so every published answer carries one mechanical verdict.

Diagnostic-only, default off (``RESEARCH_ANSWER_CONSISTENCY_GATE=on``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Sequence

CONSISTENCY_GATE_ENV = "RESEARCH_ANSWER_CONSISTENCY_GATE"

# Bounded denial vocabulary. These are the observed failure phrases from the
# §40 A/B (generation texts that denied evidence while the ledger held a
# supports row); this stays a small mechanical list, never a rule library.
EVIDENCE_STATE_DENIALS: tuple[str, ...] = (
    "没有任何证据",
    "没有已验证",
    "没有已校验",
    "没有可引用",
    "没有取得任何",
    "未取得任何",
    "无来源支持",
    "没有可用的证据",
)

POSITIVE_SUPPORT_TYPES = frozenset({"direct_support", "indirect_support"})


def consistency_gate_enabled() -> bool:
    raw = (os.getenv(CONSISTENCY_GATE_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


@dataclass(frozen=True)
class ConsistencyReport:
    unknown_evidence_ids: tuple[str, ...] = ()
    unknown_claim_ids: tuple[str, ...] = ()
    unbound_substantive_claims: tuple[str, ...] = ()
    direction_violations: tuple[str, ...] = ()
    evidence_state_conflicts: tuple[str, ...] = ()
    checked_claims: int = 0
    checked_links: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.unknown_evidence_ids
            or self.unknown_claim_ids
            or self.unbound_substantive_claims
            or self.direction_violations
            or self.evidence_state_conflicts
        )

    def codes(self) -> tuple[str, ...]:
        codes: list[str] = []
        if self.unknown_evidence_ids:
            codes.append("unknown_evidence_ids")
        if self.unknown_claim_ids:
            codes.append("unknown_claim_ids")
        if self.unbound_substantive_claims:
            codes.append("unbound_substantive_claims")
        if self.direction_violations:
            codes.append("direction_violations")
        if self.evidence_state_conflicts:
            codes.append("evidence_state_conflict")
        return tuple(codes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "codes": list(self.codes()),
            "unknown_evidence_ids": list(self.unknown_evidence_ids),
            "unknown_claim_ids": list(self.unknown_claim_ids),
            "unbound_substantive_claims": list(self.unbound_substantive_claims),
            "direction_violations": list(self.direction_violations),
            "evidence_state_conflicts": list(self.evidence_state_conflicts),
            "checked_claims": self.checked_claims,
            "checked_links": self.checked_links,
        }


def check_answer_consistency(
    *,
    candidate: str,
    claims: Sequence[Any],
    links: Sequence[Any],
    rows: Sequence[Any],
) -> ConsistencyReport:
    """One mechanical verdict: does the published answer match the ledger?

    ``claims``/``links`` are the validated binding snapshot entries;
    ``rows`` are the ``AnswerClaimBindingRow`` evidence ledger rows.
    """

    known_evidence_ids = {
        str(getattr(row, "evidence_id", "") or "") for row in rows
    } - {""}
    relation_by_evidence = {
        str(getattr(row, "evidence_id", "") or ""): str(
            getattr(row, "relation", "") or ""
        )
        for row in rows
        if str(getattr(row, "evidence_id", "") or "")
    }

    snapshot_claim_ids = {
        str(getattr(claim, "id", "") or "") for claim in claims
    } - {""}
    links_by_claim: dict[str, list[Any]] = {}
    unknown_evidence: set[str] = set()
    unknown_claims: set[str] = set()
    for link in links:
        link_claim_id = str(getattr(link, "claim_id", "") or "")
        link_evidence_id = str(getattr(link, "evidence_id", "") or "")
        if link_evidence_id and link_evidence_id not in known_evidence_ids:
            unknown_evidence.add(link_evidence_id)
        if link_claim_id and link_claim_id not in snapshot_claim_ids:
            unknown_claims.add(link_claim_id)
        links_by_claim.setdefault(link_claim_id, []).append(link)

    unbound: list[str] = []
    direction: list[str] = []
    for claim in claims:
        if str(getattr(claim, "kind", "") or "") != "factual":
            continue
        if str(getattr(claim, "status", "") or "") == "withdrawn":
            continue
        claim_id = str(getattr(claim, "id", "") or "")
        claim_links = links_by_claim.get(claim_id, [])
        if not claim_links:
            unbound.append(claim_id)
            continue
        positive = False
        for link in claim_links:
            support_type = str(getattr(link, "support_type", "") or "")
            evidence_id = str(getattr(link, "evidence_id", "") or "")
            if (
                support_type in POSITIVE_SUPPORT_TYPES
                and relation_by_evidence.get(evidence_id) == "supports"
            ):
                positive = True
                break
        if not positive:
            direction.append(claim_id)

    conflicts: list[str] = []
    ledger_has_support = any(
        str(getattr(row, "relation", "") or "") == "supports" for row in rows
    )
    text = str(candidate or "")
    if ledger_has_support:
        for phrase in EVIDENCE_STATE_DENIALS:
            if phrase in text:
                conflicts.append(phrase)

    return ConsistencyReport(
        unknown_evidence_ids=tuple(sorted(unknown_evidence)),
        unknown_claim_ids=tuple(sorted(unknown_claims)),
        unbound_substantive_claims=tuple(unbound),
        direction_violations=tuple(direction),
        evidence_state_conflicts=tuple(conflicts),
        checked_claims=sum(1 for claim in claims if getattr(claim, "kind", "") == "factual"),
        checked_links=len(links),
    )


__all__ = [
    "CONSISTENCY_GATE_ENV",
    "EVIDENCE_STATE_DENIALS",
    "ConsistencyReport",
    "check_answer_consistency",
    "consistency_gate_enabled",
]
