"""CL-M3-S2-B1-2a: the production assembly for settlement, off by default.

This module is the only place allowed to build the settlement adapter for the
real application. It exists so that "is the paid path wired?" has one answer:
the flag is read here, the configuration is checked here, and nothing else
constructs an adapter.

**Off by default, and off means absent.** With no flag the factory returns
``None``. It does not return a no-op adapter, because a no-op adapter is an
object that the rest of the application will happily treat as a working cost
gate.

**Every prerequisite is checked, not assumed.** A settlement chain needs a
durable experiment, a positive cap, configured prices, a model the experiment
pays for, an attempt budget, and one SQLite file shared by the reservation
ledger and the audit store. A typo in any of them refuses the assembly instead
of producing a chain that cannot price, cannot authorize, or silently splits
one send across two databases.

**No silent downgrade.** The adapter must be able to *claim* a send
authorization. ``AdmittedCompletion`` refuses to send when a ledger exposes no
claim, but the factory refuses earlier: an assembly that cannot hand out the
authorization is not a compliant assembly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.application.spend_settlement_adapter import SettlementLedgerAdapter
from src.infrastructure.sqlite.spend_settlement import SpendSettlementRepository
from src.llm_spend_guard import (
    SpendConfigurationError,
    experiment_cap_cny,
    experiment_id,
    require_allowed_model,
    reservation_cny,
    spend_ledger_path,
)

# One flag names the whole chain. Anything other than an explicit affirmative is
# OFF: an unset, misspelled or empty value must not enable spending.
ASSEMBLY_FLAG = "STUDY_AGENT_SETTLEMENT_ADMISSION"
_AFFIRMATIVE = frozenset({"1", "true", "on", "yes"})


class AdmissionConfigError(RuntimeError):
    """The chain cannot be assembled safely. The reason is a first-class value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SettlementAdmission:
    """A fully configured settlement chain. Constructing one spends nothing."""

    adapter: SettlementLedgerAdapter
    settlements: SpendSettlementRepository
    ledger_path: str
    experiment_id: str
    model: str
    attempts: int


def settlement_admission_enabled() -> bool:
    return os.getenv(ASSEMBLY_FLAG, "").strip().lower() in _AFFIRMATIVE


def build_settlement_admission(
    *,
    model: str,
    attempts: int = 1,
    allow_offline_fixture: bool = False,
    ledger_path: str | None = None,
) -> SettlementAdmission | None:
    """Build the chain, or ``None`` when the feature flag is off."""

    if not settlement_admission_enabled():
        return None

    if not isinstance(model, str) or not model.strip():
        raise AdmissionConfigError("model_not_configured")
    if type(attempts) is not int or attempts < 1:
        raise AdmissionConfigError("attempts_invalid")

    experiment = experiment_id()
    if not experiment:
        raise AdmissionConfigError("experiment_not_configured")
    cap = experiment_cap_cny()
    if cap is None or cap <= 0:
        raise AdmissionConfigError("cap_not_configured")

    try:
        # Fails closed when the price configuration is missing; a reservation
        # cannot be priced without it.
        reservation_cny(prompt_chars=1, max_tokens=1, attempts=1)
    except SpendConfigurationError as exc:
        raise AdmissionConfigError("pricing_not_configured") from exc
    try:
        require_allowed_model(model)
    except SpendConfigurationError as exc:
        raise AdmissionConfigError("model_not_allowed") from exc

    resolved = str(Path(ledger_path or spend_ledger_path()).expanduser().resolve())

    settlements = SpendSettlementRepository(resolved)
    adapter = SettlementLedgerAdapter(
        settlements,
        attempts=attempts,
        allow_offline_fixture=allow_offline_fixture,
    )
    claim = getattr(adapter, "claim_send_authorization", None)
    if not callable(claim):
        # A chain that cannot hand over the authorization would let the transport
        # reserve a second time. Refuse at assembly, not mid-turn.
        raise AdmissionConfigError("adapter_cannot_authorize")
    if Path(settlements.database_path) != Path(resolved):
        raise AdmissionConfigError("ledger_path_mismatch")

    return SettlementAdmission(
        adapter=adapter,
        settlements=settlements,
        ledger_path=resolved,
        experiment_id=experiment,
        model=model,
        attempts=attempts,
    )
