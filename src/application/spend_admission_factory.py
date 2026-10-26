"""CL-M3-S2-B1-2a: the production assembly for settlement and quota, off by default.

This module is the only place allowed to build the paid chain for the real
application. It exists so that "is the paid path wired?" has one answer: the flag
is read here, both tracks are assembled here, and nothing else constructs them.

**Off by default, and off means absent.** With no flag the factory returns
``None``. It does not return a no-op adapter, because a no-op adapter is an
object the rest of the application will happily treat as a working gate.

**Two tracks, both required (Q-10).** The cost adapter limits what the
experiment may reserve in money; the logical admission limits how many calls,
characters and output tokens one chat turn or one research operation may spend.
Neither substitutes for the other: a research that is still inside its money cap
must not be allowed to re-plan forever.

**The quotas are the approved trial policy, not hidden defaults.** The numbers
below are the S2-B1 offline trial values, frozen for this experiment. They are
capacity limits, not grants: existing LoopLimits, stage limits and output caps
still apply, and the stricter one wins. A different experiment changes them by
choosing new quota files; an existing quota file is immutable and a mismatched
one is refused by ``SqliteDecisionAdmission``.

**Every prerequisite is checked, not assumed.** A chain needs a durable
experiment, a positive cap, configured prices, a model the experiment pays for,
an attempt budget, one absolute SQLite file shared by the reservation ledger and
the audit store, and a logical quota file of its own (never the runtime
database). A typo refuses the assembly instead of producing a chain that cannot
price, cannot authorize, or silently splits a send across two stores.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from src.application.conversation_decision_admission import SqliteDecisionAdmission
from src.application.spend_settlement_adapter import SettlementLedgerAdapter
from src.infrastructure.sqlite.spend_settlement import SpendSettlementRepository
from src.llm_client import effective_attempts
from src.llm_spend_guard import (
    SETTLEMENT_ASSEMBLY_FLAG,
    SpendConfigurationError,
    experiment_cap_cny,
    experiment_id,
    require_allowed_model,
    reservation_cny,
    settlement_admission_enabled,
    spend_ledger_path,
)

# One flag names the whole chain. Anything other than an explicit affirmative is
# OFF: an unset, misspelled or empty value must not enable spending. The parsing
# lives in the guard so the transport's isolation check and this factory can
# never disagree about whether the chain is on.
ASSEMBLY_FLAG = SETTLEMENT_ASSEMBLY_FLAG

CHAT = "chat"
RESEARCH = "research"
_QUOTA_KINDS = frozenset({CHAT, RESEARCH})


class AdmissionConfigError(RuntimeError):
    """The chain cannot be assembled safely. The reason is a first-class value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LogicalQuota:
    """One turn's or one operation's call/character/output ceiling."""

    max_calls: int
    max_prompt_chars: int
    max_output_tokens: int


# Approved S2-B1 offline trial policy (2026-10-25). These are upper bounds for a
# single turn/operation, not additional permission.
CHAT_TRIAL_QUOTA = LogicalQuota(
    max_calls=6, max_prompt_chars=120_000, max_output_tokens=12_000
)
RESEARCH_TRIAL_QUOTA = LogicalQuota(
    max_calls=12, max_prompt_chars=240_000, max_output_tokens=24_000
)


@dataclass(frozen=True)
class SettlementAdmission:
    """A fully configured chain. Constructing one spends nothing."""

    adapter: SettlementLedgerAdapter
    settlements: SpendSettlementRepository
    logical: SqliteDecisionAdmission
    ledger_path: str
    logical_path: str
    logical_kind: str
    scope_id: str
    experiment_id: str
    model: str
    attempts: int


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def logical_admission_path(base_dir: Path, experiment: str, kind: str, scope: str) -> Path:
    """The stable per-turn/per-operation quota file.

    Reopening the same scope must open the same file: a new path after a
    reconnect would hand out a fresh budget, which is the one thing the quota
    exists to prevent.
    """

    return (
        Path(base_dir).resolve()
        / "decision-admission"
        / _digest(experiment)
        / f"{kind}-{_digest(scope)}.sqlite"
    )


def _quota_for(kind: str, quota: LogicalQuota | None) -> LogicalQuota:
    chosen = quota or (CHAT_TRIAL_QUOTA if kind == CHAT else RESEARCH_TRIAL_QUOTA)
    for value in (chosen.max_calls, chosen.max_prompt_chars, chosen.max_output_tokens):
        if type(value) is not int or value <= 0:
            raise AdmissionConfigError("quota_invalid")
    return chosen


def build_settlement_admission(
    *,
    model: str,
    kind: str,
    scope_id: str,
    attempts: int | None = None,
    allow_offline_fixture: bool = False,
    ledger_path: str | None = None,
    quota: LogicalQuota | None = None,
) -> SettlementAdmission | None:
    """Build both tracks, or ``None`` when the feature flag is off.

    ``kind`` names the quota owner: ``chat`` for one turn, ``research`` for one
    operation. ``scope_id`` is that turn's or operation's stable identifier.
    """

    if not settlement_admission_enabled():
        return None

    if kind not in _QUOTA_KINDS:
        raise AdmissionConfigError("quota_kind_invalid")
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise AdmissionConfigError("quota_scope_missing")
    if not isinstance(model, str) or not model.strip():
        raise AdmissionConfigError("model_not_configured")
    # One attempt is not a retry policy. The transport reserves the provider's
    # retries + 1 unless a caller overrides them, so a permit that authorizes a
    # single attempt refuses the send it was issued for.
    resolved_attempts = effective_attempts() if attempts is None else attempts
    if type(resolved_attempts) is not int or resolved_attempts < 1:
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
        attempts=resolved_attempts,
        allow_offline_fixture=allow_offline_fixture,
    )
    claim = getattr(adapter, "claim_send_authorization", None)
    if not callable(claim):
        # A chain that cannot hand over the authorization would let the transport
        # reserve a second time. Refuse at assembly, not mid-turn.
        raise AdmissionConfigError("adapter_cannot_authorize")
    if Path(settlements.database_path) != Path(resolved):
        raise AdmissionConfigError("ledger_path_mismatch")

    chosen = _quota_for(kind, quota)
    logical_path = logical_admission_path(
        Path(resolved).parent, experiment, kind, scope_id
    )
    # The quota store owns its directory; SqliteDecisionAdmission refuses to
    # invent a parent for an existing path.
    logical_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # The quota file must be its own database; SqliteDecisionAdmission
        # refuses the runtime database and any pre-existing foreign file.
        logical = SqliteDecisionAdmission(
            logical_path,
            max_calls=chosen.max_calls,
            max_prompt_chars=chosen.max_prompt_chars,
            max_output_tokens=chosen.max_output_tokens,
        )
    except ValueError as exc:
        raise AdmissionConfigError("logical_admission_refused") from exc

    return SettlementAdmission(
        adapter=adapter,
        settlements=settlements,
        logical=logical,
        ledger_path=resolved,
        logical_path=str(logical_path),
        logical_kind=kind,
        scope_id=scope_id,
        experiment_id=experiment,
        model=model,
        attempts=resolved_attempts,
    )
