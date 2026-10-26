"""CL-M3-S1: the `LedgerPort` that reserves through the ledger and settles into the audit.

Two authorities, one adapter:

* **money** stays with `src.llm_spend_guard.reserve_call` / `SpendLedger`. This
  adapter does not compute a reservation, does not write one, and cannot change
  one. It calls the existing entry point with the caller's own request key, so
  the send that is priced and stored is the send that will be reported later;
* **observation** goes to `SpendSettlementRepository`, which appends to its own
  table and never touches the reservation.

**Reserving without a budget is not a reservation.** ``reserve_call`` returns
``0.0`` when no cap is configured - that is "there is no ledger to charge", not
"this call is free". The adapter refuses that, and refuses any call whose
reservation row it cannot read back with a positive amount: a successful
reserve that leaves no durable row is exactly the state the cap cannot bound.

**Duplicate reservation is refused, not merged.** A second `reserve` for the
same send means two components are trying to buy the same call; the ledger
refuses the repeated key and this adapter turns that into a refusal. Buying
once and reporting twice is safe; buying twice is not.

**The request identity is bound at reserve time.** `settle` never derives a new
key: it looks the request up among the reservations it was asked to reserve, and
refuses when the key names no reservation or names more than one.
"""

from __future__ import annotations

from src.domain.runtime_entities import utc_now
from src.domain.spend_settlement import (
    COST_BASES,
    PRODUCTION_EVIDENCE_KINDS,
    SettlementEvidenceError,
    parse_evidence,
)
from src.infrastructure.sqlite.spend_ledger import SpendAdmissionRefused, SpendLedgerError
from src.infrastructure.sqlite.spend_settlement import (
    SettlementError,
    SettlementIdentityRejected,
    SpendSettlementRepository,
)
from src.llm_spend_guard import (
    SendAuthorization,
    SpendConfigurationError,
    SpendLimitExceeded,
    authorize_send,
    experiment_id,
    register_settling_owner,
    reserve_call,
)

RESERVED = "reserved"
COST_LEDGER_REFUSED = "cost_ledger_refused"
COST_UPPER_BOUND_INVALIDATED = "cost_upper_bound_invalidated"


class SettlementLedgerAdapter:
    """A `LedgerPort` with no opinion of its own about money or outcomes."""

    def __init__(
        self,
        settlements: SpendSettlementRepository,
        *,
        purpose: str = "conversation",
        allow_offline_fixture: bool = False,
        attempts: int = 1,
    ) -> None:
        if not callable(getattr(settlements, "settle", None)):
            raise ValueError("invalid settlement repository")
        if not isinstance(purpose, str) or not purpose.strip():
            raise ValueError("invalid settlement purpose")
        if type(attempts) is not int or attempts < 1:
            raise ValueError("invalid attempts")
        self._settlements = settlements
        self._purpose = purpose
        # The retry budget the reservation pays for. The provider's real retry
        # configuration must be the same number here, or the transport refuses -
        # silently widening the authorization is not an option.
        self._attempts = attempts
        # Offline fixtures are honest in tests and worthless in production: a
        # fixture proves only that the caller can type. The default refuses them,
        # and only a test harness should turn this on.
        self._allow_offline_fixture = bool(allow_offline_fixture)
        # Register the capability before any reserve can happen. See the guard's
        # module docstring: the first reservation is allowed only for an object
        # that owns a settlement store.
        register_settling_owner(self)
        # request_id -> experiment_id, from the reserve that actually happened.
        self._experiments: dict[str, str] = {}
        # request_id -> the single-use authorization issued with that reservation.
        self._authorizations: dict[str, SendAuthorization] = {}

    @property
    def settlements(self) -> SpendSettlementRepository:
        return self._settlements

    # -- LedgerPort ---------------------------------------------------------------

    def reserve(
        self,
        request_id: str,
        *,
        model: str,
        max_output_tokens: int,
        prompt_chars: int,
    ) -> str:
        """Price and persist one send through the existing ledger entry point."""

        if not isinstance(request_id, str) or not request_id:
            return COST_LEDGER_REFUSED
        experiment = experiment_id()
        if not experiment:
            # No experiment means no durable budget. "0.0" from the guard is not a
            # reservation, and this adapter will not pretend it is one.
            return COST_LEDGER_REFUSED
        if self._settlements.overruns(experiment):
            # A previous send cost more than the ceiling reserved for it. The cap
            # is already known not to bound reality; stop spending until a human
            # has looked at the observation. The reservation is not the knob.
            return COST_UPPER_BOUND_INVALIDATED
        try:
            amount_cny = reserve_call(
                prompt_chars=prompt_chars,
                max_tokens=max_output_tokens,
                attempts=self._attempts,
                purpose=self._purpose,
                model=model,
                request_key=request_id,
                # Object capability, not a boolean: only a registered adapter can
                # make the first reservation in experiment mode.
                settling_owner=self,
                # The overrun check runs inside the reservation's own write
                # transaction. Checking it here, before the call, would leave a
                # window in which an overrun observation commits unseen - the P1
                # shape the contract's :12.7 forbids.
                admission_guard=self._settlements.admission_guard,
            )
        except SpendAdmissionRefused as refused:
            return (
                COST_UPPER_BOUND_INVALIDATED
                if refused.reason == COST_UPPER_BOUND_INVALIDATED
                else COST_LEDGER_REFUSED
            )
        except (SpendLimitExceeded, SpendConfigurationError, SpendLedgerError, SettlementError):
            # A refusal is a refusal: no model call follows it.
            return COST_LEDGER_REFUSED
        if (
            isinstance(amount_cny, bool)
            or not isinstance(amount_cny, (int, float))
            or amount_cny <= 0
        ):
            return COST_LEDGER_REFUSED
        stored = self._settlements.reservation(experiment, request_id)
        if stored is None or stored.amount_micros <= 0:
            # The ledger said yes but no durable row says how much: treat the send
            # as unbound rather than as free.
            return COST_LEDGER_REFUSED
        self._experiments[request_id] = experiment
        # The authorization is issued only here, after the durable reservation
        # exists, and it re-reads that row: the bounds below describe what was
        # stored, and the amount is the stored amount.
        self._authorizations[request_id] = authorize_send(
            experiment_id=experiment,
            request_key=request_id,
            model=str(model or ""),
            prompt_chars=int(prompt_chars),
            max_tokens=int(max_output_tokens or 0),
            attempts=self._attempts,
        )
        return RESERVED

    def claim_send_authorization(self, request_id: str) -> SendAuthorization | None:
        """Hand the single-use authorization to the layer that is about to send.

        Popping is the handoff: the adapter no longer holds it, so it cannot be
        claimed twice.
        """

        return self._authorizations.pop(request_id, None)

    def settle(
        self,
        request_id: str,
        *,
        outcome: str,
        cost_micros: int | None,
        cost_basis: str | None = None,
        evidence_ref: str = "",
    ) -> None:
        """Append the observation. Raises rather than dropping the identity."""

        if cost_micros is not None and cost_basis not in COST_BASES:
            raise ValueError("invalid_cost_basis")
        if evidence_ref:
            kind, _receipt = parse_evidence(evidence_ref, request_id)
            if kind not in PRODUCTION_EVIDENCE_KINDS and not self._allow_offline_fixture:
                raise SettlementEvidenceError("evidence_fixture_not_allowed")
        experiment = self._experiment_for(request_id)
        self._settlements.settle(
            experiment,
            request_id,
            outcome=outcome,
            cost_micros=cost_micros,
            cost_basis=cost_basis,
            evidence_ref=evidence_ref,
            observed_at=utc_now(),
        )
        self._experiments.pop(request_id, None)

    # -- identity ------------------------------------------------------------------

    def _experiment_for(self, request_id: str) -> str:
        bound = self._experiments.get(request_id)
        if bound:
            return bound
        owners = self._settlements.experiments_for_request(request_id)
        if not owners:
            raise SettlementIdentityRejected("reservation_not_found")
        if len(owners) > 1:
            # The same key under two experiments is not one send. Refusing is the
            # only answer that cannot attach an observation to the wrong budget.
            raise SettlementIdentityRejected("ambiguous_request_key")
        return owners[0]
