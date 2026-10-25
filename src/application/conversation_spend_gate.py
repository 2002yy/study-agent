"""M3-QD-2d: the real-cost track, mounted where the loop already reserves.

The loop asks exactly one question of its budget - ``reserve`` - and never reports back
whether the call it paid for succeeded. That shape is sufficient for logical quota, where
a reservation is spent the moment it is taken, but not for money: "the provider answered"
and "the call died on the wire" settle differently.

So this gate does two things and no third thing. It reserves on both tracks before the
provider is touched (the stricter track decides), and it settles at the end of the turn
from the loop's own receipts. **It keeps no ledger.** ``LedgerPort``'s only production
implementation is the spend-ledger work (#259); a second implementation here would be a
second source of truth for the same money.

Settlement is deliberately not per call inside this object. The caller sees one
``DecisionResult`` per admitted call and attributes a success to a ``request_id``;
everything it cannot attribute - a cancel, a disconnect, a deadline, a thread still
running after dispatch gave up - stays reserved and is settled ``unresolved`` when the
turn closes. Refunding those would report money that was probably spent as money never
spent, which is the one accounting error this module exists to prevent.

Until #259 merges there is no production ``LedgerPort``. That is handled by construction
rather than by a stub: :class:`~src.application.conversation_turn_lifecycle.TurnLifecycle`
refuses to build without a spend port, so the failure mode is "the turn does not start"
and never "the turn runs unmetered".

**Update (CL-M3-S1).** A ``LedgerPort`` implementation now exists
(``src/application/spend_settlement_adapter.py``): it reserves through the existing
``reserve_call`` entry point and appends observations to the settlement audit. It is
deliberately **not** constructed by any production host yet - wiring the turn lifecycle
is a separate slice. What changed here is the port's vocabulary: a completed call must
carry an evidence reference, and an unresolved one reports an unknown cost (``None``)
instead of zero.
"""

from __future__ import annotations

from typing import Callable

from src.application.conversation_decision_runner import (
    COST_LEDGER_REFUSED,
    DecisionAdmission,
)
from src.domain.spend_settlement import COST_BASIS_ESTIMATED
from src.web.semantic_admission import SETTLED, UNRESOLVED, LedgerPort


class SpendGatedAdmission:
    """Reserve on the logical track and the cost track; settle once, at turn close.

    Not a frozen dataclass on purpose: the open-reservation set *is* the mutable state
    that makes a second settlement impossible. A ``request_id`` leaves ``_open`` exactly
    once, so no path - success, close, timeout, double close - can settle it twice.
    """

    def __init__(
        self,
        logical: DecisionAdmission,
        *,
        spend: LedgerPort,
        model: str,
        price_micros: Callable[[int], int],
    ) -> None:
        if not callable(getattr(logical, "reserve", None)):
            raise ValueError("invalid logical admission")
        if not callable(getattr(spend, "reserve", None)) or not callable(
            getattr(spend, "settle", None)
        ):
            raise ValueError("invalid spend port")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("invalid spend model")
        if not callable(price_micros):
            raise ValueError("invalid spend pricing")
        self._logical = logical
        self._spend = spend
        self._model = model
        self._price = price_micros
        # request_id -> the output-token estimate that was reserved. Insertion order is
        # the order in which money may have been spent.
        self._open: dict[str, int] = {}

    # --- DecisionAdmission -------------------------------------------------------------

    def reserve(self, request_id: str, prompt_chars: int, output_tokens: int) -> str:
        verdict = self._logical.reserve(request_id, prompt_chars, output_tokens)
        if verdict != "reserved":
            return verdict
        try:
            spend_verdict = self._spend.reserve(
                request_id,
                model=self._model,
                max_output_tokens=output_tokens,
                prompt_chars=prompt_chars,
            )
        except Exception:
            # An unreachable ledger is not free money. Propagating makes the runner report
            # ``admission_unavailable`` and the request is never sent; the logical slot
            # stays spent, which is the conservative half of the two.
            raise
        if spend_verdict != "reserved":
            # Nothing was sent, so there is nothing to settle on the cost track. The
            # logical reservation is not refunded - that ledger has no refund API by
            # design, and inventing one here would be the third ledger.
            return COST_LEDGER_REFUSED
        self._open[request_id] = output_tokens
        return "reserved"

    # --- settlement, called by the host exactly once per turn --------------------------

    def settle_completed(
        self,
        request_id: str,
        *,
        evidence_ref: str,
        cost_micros: int | None = None,
    ) -> bool:
        """Settle one call the loop reported as completed. ``False`` = already settled.

        ``evidence_ref`` is not optional: a completed call is a claim that needs a
        receipt naming this send (contract §12.2). ``cost_micros=None`` means
        "price the reservation's estimate", not "unknown" - an unknown outcome is
        settled by :meth:`settle_unresolved`, and the two must not share a
        default.
        """

        estimate = self._open.get(request_id)
        if estimate is None:
            return False
        cost = self._price(estimate) if cost_micros is None else cost_micros
        if type(cost) is not int or cost < 0:
            raise ValueError("invalid spend cost")
        # The durable port must settle idempotently by request_id. A failure
        # (including an ambiguous commit acknowledgement) cannot drop the
        # pending identity: the host may retry or reconcile it.
        self._spend.settle(
            request_id,
            outcome=SETTLED,
            cost_micros=cost,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=evidence_ref,
        )
        del self._open[request_id]
        return True

    def settle_unresolved(self) -> tuple[str, ...]:
        """Close the turn. Every still-open call never reported an outcome.

        Returns the ids, so the caller can record in the turn receipt which calls are
        unresolved instead of asserting that everything was priced. The cost is
        ``None`` rather than ``0``: unknown is not free (contract §12.4).
        """

        open_ids = tuple(self._open)
        for request_id in open_ids:
            # The port is responsible for durable, request-idempotent settlement.
            # Keep this identity on failure so the caller can retry settlement.
            self._spend.settle(
                request_id, outcome=UNRESOLVED, cost_micros=None, cost_basis=None
            )
            del self._open[request_id]
        return open_ids

    @property
    def open_request_ids(self) -> tuple[str, ...]:
        """Reserved on both tracks, not yet settled. Empty once the turn is closed."""
        return tuple(self._open)
