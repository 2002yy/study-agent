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

# How strong the binding is, stated rather than implied. ``host_attested`` means
# a trusted execution boundary recorded the outcome of this send; it is not a
# provider invoice, a signature, or proof of what was billed. ``test_only`` is a
# fixture whose trust is whatever the test harness says it is, so a production
# adapter must refuse it.
EVIDENCE_LEVEL_HOST_ATTESTED = "host_attested"
EVIDENCE_LEVEL_TEST_ONLY = "test_only"
EVIDENCE_LEVELS = {
    EVIDENCE_PROVIDER_RESULT: EVIDENCE_LEVEL_HOST_ATTESTED,
    EVIDENCE_WORKER_RECEIPT: EVIDENCE_LEVEL_HOST_ATTESTED,
    EVIDENCE_OFFLINE_FIXTURE: EVIDENCE_LEVEL_TEST_ONLY,
}
PRODUCTION_EVIDENCE_KINDS = frozenset(
    {EVIDENCE_PROVIDER_RESULT, EVIDENCE_WORKER_RECEIPT}
)


def evidence_level(kind: str) -> str:
    """The declared strength of one evidence kind (refuses an unknown kind)."""

    try:
        return EVIDENCE_LEVELS[kind]
    except KeyError:
        raise SettlementEvidenceError("evidence_kind_unknown") from None

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
    """Return ``(kind, receipt)``, or refuse because it is not this send's.

    The separator is the **last** ``#``: a request key may legitimately contain
    one (``operation#round#stage`` is the admission layer's shape), while a
    receipt may not. Splitting on the first ``#`` would read that key as
    ``operation`` and reject its own evidence.
    """

    if not isinstance(reference, str) or not reference:
        raise SettlementEvidenceError("evidence_missing")
    kind, separator, rest = reference.partition(":")
    if not separator or kind not in EVIDENCE_KINDS:
        raise SettlementEvidenceError("evidence_kind_unknown")
    cut = rest.rfind("#")
    if cut <= 0 or cut == len(rest) - 1:
        raise SettlementEvidenceError("evidence_receipt_missing")
    bound_key, receipt = rest[:cut], rest[cut + 1 :]
    if bound_key != request_key:
        raise SettlementEvidenceError("evidence_not_bound_to_request")
    if any(character.isspace() for character in receipt) or len(receipt) > 200:
        raise SettlementEvidenceError("evidence_receipt_malformed")
    return kind, receipt
