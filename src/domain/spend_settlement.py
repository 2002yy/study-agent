"""CL-M3-S1: the vocabulary of a settlement observation (contract §12).

A settlement says what was later learned about one *real send*. The vocabulary
lives here, in the domain, because three layers have to agree on it: the audit
store (SQLite), the adapter that speaks to the ledger, and the two call sites
that report outcomes. If each spelled ``"settled"`` and its evidence format for
itself, the first disagreement would be discovered by a database CHECK rather
than by a test.

**Evidence is a binding, not a comment.** ``evidence_ref`` names the *kind* of
receipt, the *request* it belongs to, and the receipt itself:
``<kind>:<request_key>#<receipt>``. The request key is inside the reference so
that a receipt issued for one send cannot be presented for another. Whether the
receipt is trustworthy is a question for the caller; whether it belongs to this
send is a question this module can answer, and does.
"""

from __future__ import annotations

# Outcomes. ``unresolved`` is the honest default: we do not know. ``failed`` is
# reserved for a verifiable failure receipt; an SDK exception is not one.
SETTLEMENT_UNRESOLVED = "unresolved"
SETTLEMENT_SETTLED = "settled"
SETTLEMENT_FAILED = "failed"
SETTLEMENT_OUTCOMES = frozenset(
    {SETTLEMENT_UNRESOLVED, SETTLEMENT_SETTLED, SETTLEMENT_FAILED}
)

# How a recorded cost was obtained. Even ``measured_usage`` is a priced
# estimate, not a provider invoice (contract §12.4).
COST_BASIS_ESTIMATED = "estimated"
COST_BASIS_MEASURED_USAGE = "measured_usage"
COST_BASES = frozenset({COST_BASIS_ESTIMATED, COST_BASIS_MEASURED_USAGE})

EVIDENCE_PROVIDER_RESULT = "provider_result"
EVIDENCE_WORKER_RECEIPT = "worker_receipt"
EVIDENCE_OFFLINE_FIXTURE = "offline_fixture"
EVIDENCE_KINDS = frozenset(
    {EVIDENCE_PROVIDER_RESULT, EVIDENCE_WORKER_RECEIPT, EVIDENCE_OFFLINE_FIXTURE}
)

# Exactly one correction, once. ``settled`` is final for this phase: measured
# usage arriving later is a separate reconciliation, not a rewrite of history.
ALLOWED_TRANSITIONS = frozenset({(SETTLEMENT_UNRESOLVED, SETTLEMENT_SETTLED)})


class SettlementEvidenceError(ValueError):
    """An evidence reference that does not name the send it claims."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def evidence_ref(*, kind: str, request_key: str, receipt: str) -> str:
    """Build the canonical binding. ``receipt`` must be a single non-empty token."""

    if kind not in EVIDENCE_KINDS:
        raise SettlementEvidenceError("evidence_kind_unknown")
    if not isinstance(request_key, str) or not request_key:
        raise SettlementEvidenceError("evidence_request_key_missing")
    if not isinstance(receipt, str) or not receipt.strip():
        raise SettlementEvidenceError("evidence_receipt_missing")
    if "#" in receipt or any(character.isspace() for character in receipt):
        raise SettlementEvidenceError("evidence_receipt_malformed")
    if len(receipt) > 200:
        raise SettlementEvidenceError("evidence_receipt_malformed")
    return f"{kind}:{request_key}#{receipt}"


def parse_evidence(reference: object, request_key: str) -> tuple[str, str]:
    """Return ``(kind, receipt)``, or refuse because it is not this send's."""

    if not isinstance(reference, str) or not reference:
        raise SettlementEvidenceError("evidence_missing")
    kind, separator, rest = reference.partition(":")
    if not separator or kind not in EVIDENCE_KINDS:
        raise SettlementEvidenceError("evidence_kind_unknown")
    bound_key, separator, receipt = rest.partition("#")
    if not separator or not receipt:
        raise SettlementEvidenceError("evidence_receipt_missing")
    if bound_key != request_key:
        raise SettlementEvidenceError("evidence_not_bound_to_request")
    if any(character.isspace() for character in receipt) or len(receipt) > 200:
        raise SettlementEvidenceError("evidence_receipt_malformed")
    return kind, receipt
