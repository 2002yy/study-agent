"""Pre-request, conservative spend accounting for paid runs.

A verified hard cap must exist *before* the request, not in the bill afterwards.
When a cap is configured, every paid model/vision call reserves its **worst
case** cost (bounded retries included) and is refused when the reservation would
exceed the remaining budget.

Two ledgers can be in force at the same time, and both must pass:

* the **process** budget (``LLM_SPEND_CAP_CNY``) - a process-global counter, fine
  for a single long-lived server but forgotten on restart;
* the **experiment** budget (``LLM_SPEND_EXPERIMENT_ID`` +
  ``LLM_SPEND_EXPERIMENT_CAP_CNY``) - a durable reservation ledger in the
  runtime SQLite database, shared by every process that opens the same absolute
  path and unchanged by a restart.  It is the one an acceptance run is judged
  against, so it is authoritative; the process counter is a mirror used for
  reporting.

Fail-closed rules:

* a configured cap without explicit pricing refuses every call;
* waiting/uncertain costs are never assumed to be zero (prompt size is charged
  as an upper bound, output as ``max_tokens``, attempts as ``retries + 1``);
* with an experiment budget enabled, a call that cannot name the experiment
  invocation it belongs to, or whose ledger cannot be written, is refused -
  never charged to the process counter instead;
* reservations are never refunded, so the caps bound *reserved* cost rather than
  a post-hoc estimate.

Money is compared as integer micro-CNY (1 CNY = 1_000_000 micro-CNY).

Configuration (no defaults are invented):

* ``LLM_SPEND_CAP_CNY``               - budget for this process, e.g. ``10``
* ``LLM_SPEND_EXPERIMENT_ID``         - durable experiment identity, e.g. ``ia1a-samples``
* ``LLM_SPEND_EXPERIMENT_CAP_CNY``    - durable cap for that experiment (falls back
                                        to ``LLM_SPEND_CAP_CNY``)
* ``LLM_SPEND_LEDGER_DB``             - absolute ledger path override; default is the
                                        runtime database (``STUDY_AGENT_RUNTIME_DB``)
* ``LLM_SPEND_INPUT_CNY_PER_MTOK``    - CNY per 1M input tokens
* ``LLM_SPEND_OUTPUT_CNY_PER_MTOK``   - CNY per 1M output tokens
* ``LLM_SPEND_DEFAULT_MAX_TOKENS``    - used when a request omits max_tokens
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import threading
from typing import Iterator

from src.infrastructure.sqlite.spend_ledger import (
    MICROS_PER_CNY,
    AdmissionGuard,
    SpendAdmissionRefused,
    SpendCapExceeded,
    SpendLedger,
    SpendLedgerConflict,
    SpendLedgerError,
    SpendLedgerUnavailable,
    cny_to_micros,
)

__all__ = [
    "DEFAULT_OUTPUT_TOKENS",
    "SpendCapExceeded",
    "SpendConfigurationError",
    "SpendIdentity",
    "SpendAdmissionRefused",
    "SpendAuthorizationError",
    "SendAuthorization",
    "SpendLedgerConflict",
    "SpendLedgerError",
    "SpendLedgerUnavailable",
    "SpendLimitExceeded",
    "SpendScope",
    "allowed_models",
    "compose_request_key",
    "new_scope",
    "pop_scope",
    "pre_reserved_send",
    "push_scope",
    "authorize_send",
    "serialized_request_chars",
    "current_identity",
    "current_scope",
    "experiment_spend",
    "remaining_cny",
    "reservation_cny",
    "require_allowed_model",
    "reserve_call",
    "reset_spend",
    "spend_cap_cny",
    "spend_identity",
    "spend_scope",
    "spent_cny",
]

DEFAULT_OUTPUT_TOKENS = 4_096


class SpendLimitExceeded(RuntimeError):
    """Raised instead of sending a request that could exceed the paid cap."""


class SpendConfigurationError(RuntimeError):
    """A cap is configured but the pricing needed to enforce it is missing."""


_lock = threading.Lock()
_reserved_cny = 0.0


@dataclass(frozen=True)
class SpendIdentity:
    """What a paid call belongs to: the experiment invocation, not just a task.

    ``task_name`` alone is not enough - two research runs can both call
    ``deep_planner``. The identity is composed with the run/operation so the same
    task in different work is never mistaken for the same paid request.
    """

    run_id: str = ""
    operation_id: str = ""
    invocation: str = ""
    #: The experiment this work is authorized to spend from. Empty means "not
    #: authorized", which the guard refuses while an experiment budget is on.
    experiment: str = ""

    def describe(self) -> str:
        return (
            f"experiment={self.experiment or '-'} run={self.run_id or '-'} "
            f"op={self.operation_id or '-'} inv={self.invocation or '-'}"
        )


_identity: ContextVar[SpendIdentity | None] = ContextVar("llm_spend_identity", default=None)


@contextmanager
def spend_identity(
    *,
    run_id: str = "",
    operation_id: str = "",
    invocation: str = "",
    experiment: str = "",
) -> Iterator[SpendIdentity]:
    """Bind the current paid calls to one experiment invocation.

    A caller that retries the *same* logical call must reuse the same
    ``invocation``; a genuinely new call must use a new one. Re-using an
    invocation for a different request is refused by the ledger, so a retry can
    never borrow a reservation that belongs to another request.
    """

    identity = SpendIdentity(
        run_id=str(run_id or ""),
        operation_id=str(operation_id or ""),
        invocation=str(invocation or ""),
        experiment=str(experiment or ""),
    )
    token = _identity.set(identity)
    try:
        yield identity
    finally:
        _identity.reset(token)


def current_identity() -> SpendIdentity | None:
    return _identity.get()


class SpendScope:
    """Names every paid call made inside one unit of work.

    A single ``request_key`` cannot cover a unit of work that makes many calls:
    the planner calls the model once per round, and each of those is a separate
    paid send. The scope numbers them, so every call gets a globally distinct
    key (experiment / run / operation / purpose / invocation / call) without the
    caller threading a key through every layer.

    Numbering is per scope entry, not per call identity: re-entering the scope
    (for example retrying the whole step) numbers from the start again, and the
    ledger refuses the repeated key instead of treating it as free.
    """

    def __init__(
        self, *, run_id: str, operation_id: str, purpose: str, experiment: str = ""
    ) -> None:
        self.run_id = str(run_id or "")
        self.operation_id = str(operation_id or "")
        self.purpose = str(purpose or "")
        self.experiment = str(experiment or "")
        self._calls = 0

    def next_key(self, purpose: str) -> str:
        self._calls += 1
        identity = SpendIdentity(
            run_id=self.run_id,
            operation_id=self.operation_id,
            invocation=str(self._calls),
            experiment=self.experiment,
        )
        return compose_request_key(
            purpose=purpose or self.purpose or "llm", identity=identity
        )

    def describe(self) -> str:
        return (
            f"experiment={self.experiment or '-'} run={self.run_id or '-'} "
            f"op={self.operation_id or '-'} purpose={self.purpose or '-'}"
        )


_scope: ContextVar[SpendScope | None] = ContextVar("llm_spend_scope", default=None)

# The admission layer that owns the reservation for a send holds an authorization
# here for the duration of the actual call. The transport is then allowed to send,
# but not to reserve again: two reservations for one send is two charges for one
# answer. The authorization is a signed, single-use record of the *bounds* that
# were reserved, not a bare key - a key proves nothing about whether a
# reservation exists or how large the real request may be.
_active_authorization: ContextVar[SendAuthorization | None] = ContextVar(
    "llm_spend_send_authorization", default=None
)
_consumed_authorizations: set[str] = set()
_AUTHORIZATION_SECRET = secrets.token_bytes(32)


class SpendAuthorizationError(SpendConfigurationError):
    """A send that is not covered by the reservation it claims.

    The reason is a first-class attribute: "missing", "forged", "already used"
    and "beyond the reserved bound" are four different production incidents, and
    a caller that cannot tell them apart will fix the wrong one.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SendAuthorization:
    """Proof that one send was reserved, and within which bounds.

    Issued only after a durable reservation succeeded. The token is an HMAC over
    the fields, so a hand-built instance cannot pass :func:`pre_reserved_send`;
    the guard keeps a consumption set, so one authorization authorizes one send.
    """

    experiment_id: str
    request_key: str
    model: str
    prompt_chars: int
    max_tokens: int
    attempts: int
    reserved_cny: float
    token: str = ""


def _authorization_payload(
    *,
    experiment_id: str,
    request_key: str,
    model: str,
    prompt_chars: int,
    max_tokens: int,
    attempts: int,
    reserved_cny: float,
) -> str:
    return json.dumps(
        {
            "experiment_id": experiment_id,
            "request_key": request_key,
            "model": model,
            "prompt_chars": int(prompt_chars),
            "max_tokens": int(max_tokens),
            "attempts": int(attempts),
            "reserved_cny": round(float(reserved_cny), 12),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def authorize_send(
    *,
    experiment_id: str,
    request_key: str,
    model: str,
    prompt_chars: int,
    max_tokens: int,
    attempts: int,
    reserved_cny: float,
) -> SendAuthorization:
    """Issue the single-use authorization for a send that was just reserved."""

    payload = _authorization_payload(
        experiment_id=experiment_id,
        request_key=request_key,
        model=model,
        prompt_chars=prompt_chars,
        max_tokens=max_tokens,
        attempts=attempts,
        reserved_cny=reserved_cny,
    )
    return SendAuthorization(
        experiment_id=experiment_id,
        request_key=request_key,
        model=model,
        prompt_chars=int(prompt_chars),
        max_tokens=int(max_tokens),
        attempts=int(attempts),
        reserved_cny=float(reserved_cny),
        token=hmac.new(_AUTHORIZATION_SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest(),
    )


def _verify_authorization(authorization: object) -> SendAuthorization:
    if not isinstance(authorization, SendAuthorization):
        raise SpendAuthorizationError("send_authorization_missing")
    payload = _authorization_payload(
        experiment_id=authorization.experiment_id,
        request_key=authorization.request_key,
        model=authorization.model,
        prompt_chars=authorization.prompt_chars,
        max_tokens=authorization.max_tokens,
        attempts=authorization.attempts,
        reserved_cny=authorization.reserved_cny,
    )
    expected_token = hmac.new(
        _AUTHORIZATION_SECRET, payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_token, str(authorization.token or "")):
        raise SpendAuthorizationError("send_authorization_forged")
    if authorization.token in _consumed_authorizations:
        raise SpendAuthorizationError("send_authorization_consumed")
    return authorization


@contextmanager
def pre_reserved_send(authorization: SendAuthorization) -> Iterator[SendAuthorization]:
    """Authorize exactly one send inside the reservation it was issued for.

    Entry consumes the authorization. A forged token, a second use, or a call
    outside the reserved bounds is refused by :func:`reserve_call` *before* the
    transport sends anything.
    """

    verified = _verify_authorization(authorization)
    with _lock:
        _consumed_authorizations.add(verified.token)
    token = _active_authorization.set(verified)
    try:
        yield verified
    finally:
        _active_authorization.reset(token)


def serialized_request_chars(payload: object) -> int:
    """Conservative character count of a request, using the transport's own proxy.

    One accounting function for the admission layer and the transport: if each
    computed its own, the outer reservation would be measured in a unit the inner
    check does not use, and "within the bound" would be a coincidence.
    """

    return len(json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str))


def new_scope(
    *, run_id: str, operation_id: str = "", purpose: str = "", experiment: str = ""
) -> SpendScope:
    """Build a scope without binding it (see :func:`push_scope`)."""

    return SpendScope(
        run_id=run_id, operation_id=operation_id, purpose=purpose, experiment=experiment
    )


def push_scope(scope: SpendScope):
    """Bind a scope and return the token that restores the previous one."""

    return _scope.set(scope)


def pop_scope(token) -> None:
    """Restore the previous scope.

    An async generator can be resumed or closed in a different context than the
    one that set the scope, and ``ContextVar.reset`` refuses a foreign token. In
    that case the scope is cleared instead: an unbound scope fails closed, while
    a stale scope would charge calls to the wrong unit of work.
    """

    try:
        _scope.reset(token)
    except ValueError:
        _scope.set(None)


@contextmanager
def spend_scope(
    *, run_id: str, operation_id: str = "", purpose: str = "", experiment: str = ""
) -> Iterator[SpendScope]:
    """Bind one unit of work so every paid call inside it is named."""

    scope = new_scope(
        run_id=run_id, operation_id=operation_id, purpose=purpose, experiment=experiment
    )
    token = push_scope(scope)
    try:
        yield scope
    finally:
        pop_scope(token)


def current_scope() -> SpendScope | None:
    return _scope.get()


def reset_spend() -> None:
    """Clear the *process* counter (tests and process start).

    The durable experiment ledger is deliberately not resettable: reservations
    are the evidence that a budget was never exceeded, so deleting them to
    restore headroom would destroy exactly the guarantee they exist for. A new
    experiment means a new ``LLM_SPEND_EXPERIMENT_ID``.
    """

    global _reserved_cny
    with _lock:
        _reserved_cny = 0.0
        # Authorizations are process-local and single-use; a reset (tests, a new
        # experiment) starts a new generation of them.
        _consumed_authorizations.clear()


def _float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise SpendConfigurationError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < 0:
        raise SpendConfigurationError(f"{name} must be a finite non-negative number")
    return value


def spend_cap_cny() -> float | None:
    return _float_env("LLM_SPEND_CAP_CNY")


def spent_cny() -> float:
    return _reserved_cny


def remaining_cny() -> float | None:
    cap = spend_cap_cny()
    return None if cap is None else max(0.0, cap - _reserved_cny)


def allowed_models() -> frozenset[str] | None:
    """The model ids a paid run may use, or None when unrestricted.

    ``LLM_EXPERIMENT_ALLOWED_MODELS`` pins an experiment to specific model ids.
    It exists because a profile is not a model: the router may pick ``pro`` for a
    hard question while the reservation was computed for a cheaper one. A
    mismatch is refused before the request - never silently re-routed, and never
    "fallen back" to a bigger model.
    """

    raw = os.getenv("LLM_EXPERIMENT_ALLOWED_MODELS", "").strip()
    if not raw:
        return None
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def require_allowed_model(model: str, *, purpose: str = "") -> str:
    """Refuse a paid call whose resolved model is not allowed for this run."""

    allowed = allowed_models()
    if allowed is None:
        return model
    if str(model) not in allowed:
        raise SpendConfigurationError(
            f"model {model!r} is not allowed for this experiment "
            f"(allowed: {', '.join(sorted(allowed))})"
            + (f" for {purpose}" if purpose else "")
            + "; the call is refused instead of falling back to another model"
        )
    return model


def experiment_id() -> str:
    return os.getenv("LLM_SPEND_EXPERIMENT_ID", "").strip()


def experiment_cap_cny() -> float | None:
    """The durable cap for the experiment, falling back to the process cap."""

    raw = os.getenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "").strip()
    if raw:
        return _float_env("LLM_SPEND_EXPERIMENT_CAP_CNY")
    return spend_cap_cny()


def _ledger_path() -> str:
    override = os.getenv("LLM_SPEND_LEDGER_DB", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise SpendConfigurationError("LLM_SPEND_LEDGER_DB must be an absolute path")
        return str(path)
    # The runtime database is the one place every process already agrees on; a
    # ledger in a per-worktree file would give each worktree its own "cap".
    from src.application.runtime_repository import runtime_database_path

    return str(Path(runtime_database_path()).expanduser().resolve())


_ledger_cache: dict[str, SpendLedger] = {}
# Its own lock: the reservation path already holds `_lock`, so re-entering it
# here would deadlock the caller.
_ledger_lock = threading.Lock()


def _ledger() -> SpendLedger:
    path = _ledger_path()
    with _ledger_lock:
        ledger = _ledger_cache.get(path)
        if ledger is None:
            ledger = SpendLedger(path)
            _ledger_cache[path] = ledger
    return ledger


def _pricing_fingerprint() -> str:
    """Identify the prices a reservation was computed with.

    A different configuration must be detected rather than silently reusing a
    budget that may have been approved under different (possibly cheaper) prices.
    """

    input_price, output_price = _pricing()
    payload = f"{input_price:.10f}|{output_price:.10f}|{_output_upper_bound(None)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def compose_request_key(
    *,
    purpose: str,
    attempt: str = "1",
    identity: SpendIdentity | None = None,
) -> str:
    """Build the ``request_key`` for one actual send.

    The key names experiment / run / operation / task / attempt, so two research
    runs that both call ``deep_planner`` can never collide, and a retry of a
    request that was already sent must pass a new ``attempt`` (its first send may
    already have been billed). ``identity`` defaults to the bound
    :func:`spend_identity`.
    """

    resolved = identity if identity is not None else _identity.get()
    if resolved is None or not (resolved.run_id or resolved.operation_id):
        raise SpendConfigurationError(
            "an experiment budget is enabled but this call names no run/operation; "
            "bind spend_identity(...) or pass an explicit request_key"
        )
    return "|".join(
        [
            experiment_id() or "-",
            resolved.run_id or "-",
            resolved.operation_id or "-",
            purpose or "-",
            resolved.invocation or "-",
            str(attempt or "1"),
        ]
    )


def _pricing() -> tuple[float, float]:
    input_price = _float_env("LLM_SPEND_INPUT_CNY_PER_MTOK")
    output_price = _float_env("LLM_SPEND_OUTPUT_CNY_PER_MTOK")
    if input_price is None or output_price is None:
        # Fail closed: without explicit pricing the cap cannot be enforced.
        raise SpendConfigurationError(
            "LLM_SPEND_CAP_CNY requires LLM_SPEND_INPUT_CNY_PER_MTOK and "
            "LLM_SPEND_OUTPUT_CNY_PER_MTOK"
        )
    return input_price, output_price


def _output_upper_bound(max_tokens: int | None) -> int:
    if isinstance(max_tokens, int) and max_tokens > 0:
        return max_tokens
    raw = os.getenv("LLM_SPEND_DEFAULT_MAX_TOKENS", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SpendConfigurationError(
                "LLM_SPEND_DEFAULT_MAX_TOKENS must be an integer"
            ) from exc
        if value > 0:
            return value
    return DEFAULT_OUTPUT_TOKENS


def enforce_output_limit(max_tokens: int | None) -> int | None:
    """Give capped model requests the actual output limit used by the ledger."""
    if spend_cap_cny() is None and not experiment_id():
        return max_tokens
    if max_tokens is not None and (
        not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0
    ):
        raise SpendConfigurationError("capped model calls require a positive max_tokens")
    return _output_upper_bound(max_tokens)


def reservation_cny(*, prompt_chars: int, max_tokens: int | None, attempts: int) -> float:
    """Worst-case cost of one call and its bounded retries."""

    input_price, output_price = _pricing()
    prompt_tokens_upper = max(0, int(prompt_chars))
    output_tokens_upper = _output_upper_bound(max_tokens)
    per_attempt = (
        prompt_tokens_upper / 1_000_000 * input_price
        + output_tokens_upper / 1_000_000 * output_price
    )
    return max(1, int(attempts)) * per_attempt


def reserve_call(
    *,
    prompt_chars: int,
    max_tokens: int | None,
    attempts: int = 1,
    purpose: str = "llm",
    model: str = "",
    request_key: str | None = None,
    identity: SpendIdentity | None = None,
    admission_guard: AdmissionGuard | None = None,
) -> float:
    """Reserve the worst case before a request; raise when it cannot fit.

    Both budgets must accept the call. The durable experiment reservation is
    written *before* the process mirror is advanced, and neither is ever
    refunded: an unverified refund could turn the cap into a post-hoc estimate,
    which this module exists to prevent.

    The process lock is held across the durable write on purpose. Paid calls are
    rare and serialising them here is exactly what the two caps mean; without it
    two threads could each pass the process check and then both write.
    """

    cap = spend_cap_cny()
    experiment = experiment_id()
    experiment_cap = experiment_cap_cny() if experiment else None

    # The admission layer holds a signed authorization for this exact send. The
    # transport may send, but only within the reserved bounds, and it must not
    # reserve a second time. An explicit *different* key is another send and is
    # refused rather than merged.
    active = _active_authorization.get()
    if active is not None:
        if request_key is not None and request_key != active.request_key:
            raise SpendAuthorizationError("send_authorization_key_mismatch")
        if str(model or "") != active.model:
            raise SpendAuthorizationError("send_authorization_model_mismatch")
        if max(0, int(prompt_chars)) > active.prompt_chars:
            raise SpendAuthorizationError("send_authorization_bound_exceeded")
        if max_tokens is not None and int(max_tokens) > active.max_tokens:
            raise SpendAuthorizationError("send_authorization_bound_exceeded")
        if max(1, int(attempts)) > active.attempts:
            raise SpendAuthorizationError("send_authorization_bound_exceeded")
        return 0.0

    if cap is None and experiment_cap is None:
        return 0.0
    if experiment and experiment_cap is None:
        raise SpendConfigurationError(
            "LLM_SPEND_EXPERIMENT_ID is set without LLM_SPEND_EXPERIMENT_CAP_CNY "
            "and without LLM_SPEND_CAP_CNY; the experiment cap cannot be inferred"
        )
    reservation = reservation_cny(
        prompt_chars=prompt_chars, max_tokens=max_tokens, attempts=attempts
    )
    global _reserved_cny
    with _lock:
        if cap is not None and _reserved_cny + reservation > cap:
            raise SpendLimitExceeded(
                f"spend cap reached for {purpose}: reserved={_reserved_cny:.4f} "
                f"next={reservation:.4f} cap={cap:.4f} CNY"
            )
        if experiment and experiment_cap is not None:
            resolved_identity = identity if identity is not None else _identity.get()
            if resolved_identity is None:
                scope = _scope.get()
                if scope is not None:
                    resolved_identity = SpendIdentity(
                        run_id=scope.run_id,
                        operation_id=scope.operation_id,
                        experiment=scope.experiment,
                    )
            # An explicit key is not authorization: a call may only spend from the
            # experiment if the work it belongs to was declared as part of it.
            if resolved_identity is None or resolved_identity.experiment != experiment:
                raise SpendConfigurationError(
                    "an experiment budget is enabled but this call is not authorized "
                    f"for it (bound experiment: "
                    f"{resolved_identity.experiment if resolved_identity else '-'}); "
                    "bind spend_scope(..., experiment=...) for the authorized work"
                )
            if not request_key:
                scope = _scope.get()
                if scope is None:
                    raise SpendConfigurationError(
                        "an experiment budget is enabled but this call names no "
                        "invocation; bind spend_scope(...) (or pass request_key)"
                    )
                request_key = scope.next_key(purpose)
            amount_micros = cny_to_micros(reservation)
            ledger = _ledger()
            ledger.ensure_experiment(
                experiment,
                cap_micros=cny_to_micros(experiment_cap),
                pricing_fingerprint=_pricing_fingerprint(),
                now=_utc_now(),
            )
            try:
                ledger.reserve(
                    experiment,
                    request_key=request_key,
                    amount_micros=amount_micros,
                    purpose=purpose,
                    model=model,
                    identity=(resolved_identity.describe() if resolved_identity else ""),
                    now=_utc_now(),
                    admission_guard=admission_guard,
                )
            except SpendCapExceeded as exc:
                # Callers already handle one "the cap stopped this call" signal.
                raise SpendLimitExceeded(str(exc)) from exc
        _reserved_cny += reservation
    return reservation


def experiment_spend(experiment: str | None = None) -> dict[str, int] | None:
    """Durable totals for acceptance evidence. There is no reset by design."""

    resolved = experiment or experiment_id()
    if not resolved:
        return None
    return _ledger().experiment_spend(resolved)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def micros_to_cny(micros: int) -> float:
    return int(micros) / MICROS_PER_CNY
