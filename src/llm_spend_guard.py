"""Pre-request, conservative spend accounting for paid runs.

A verified hard cap must exist *before* the request, not in the bill afterwards.
When ``LLM_SPEND_CAP_CNY`` is configured, every paid model/vision call reserves
its **worst case** cost (bounded retries included) and is refused when the
reservation would exceed the remaining budget.  The ledger is process-global, so
a multi-scenario acceptance run shares one cap.

Fail-closed rules:

* a configured cap without explicit pricing refuses every call;
* waiting/uncertain costs are never assumed to be zero (prompt size is charged
  as an upper bound, output as ``max_tokens``, attempts as ``retries + 1``).

Configuration (no defaults are invented):

* ``LLM_SPEND_CAP_CNY``               - total budget for this process, e.g. ``10``
* ``LLM_SPEND_INPUT_CNY_PER_MTOK``    - CNY per 1M input tokens
* ``LLM_SPEND_OUTPUT_CNY_PER_MTOK``   - CNY per 1M output tokens
* ``LLM_SPEND_DEFAULT_MAX_TOKENS``    - used when a request omits max_tokens
"""

from __future__ import annotations

import math
import os
import threading
import uuid
from contextvars import ContextVar

DEFAULT_OUTPUT_TOKENS = 4_096


class SpendLimitExceeded(RuntimeError):
    """Raised instead of sending a request that could exceed the paid cap."""


class SpendConfigurationError(RuntimeError):
    """A cap is configured but the pricing needed to enforce it is missing."""


_lock = threading.Lock()
_reserved_cny = 0.0

#: Optional durable backend (Async Deep-1A). When set, calls made inside a bound
#: authorization scope are reserved in SQLite and survive a process restart.
_ledger: object | None = None
_account_id = "account"
_scope: ContextVar[tuple[str, str] | None] = ContextVar("llm_spend_scope", default=None)


def configure_ledger(repository: object | None, *, account_id: str = "account") -> None:
    """Install the durable ledger used for authorization-scoped paid calls."""

    global _ledger, _account_id
    _ledger = repository
    _account_id = account_id


def bind_scope(authorization_id: str, scope_id: str):
    """Bind the current paid calls to one authorization/run scope."""

    return _scope.set((str(authorization_id), str(scope_id)))


def reset_scope(token: object) -> None:
    _scope.reset(token)  # type: ignore[arg-type]


def current_scope() -> tuple[str, str] | None:
    return _scope.get()


def reset_spend() -> None:
    """Clear the ledger (tests and process start)."""

    global _reserved_cny
    with _lock:
        _reserved_cny = 0.0


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
    call_id: str | None = None,
) -> float:
    """Reserve the worst case before a request; raise when it cannot fit.

    With a durable ledger configured **and** an authorization scope bound, the
    reservation is written to SQLite (authoritative across restarts).  Calls
    outside any scope keep the process-level conservative counter.
    """

    scope = _scope.get()
    if scope is not None:
        if _ledger is None:
            # F3: an authorized scope must never fall back to the memory ledger.
            raise SpendConfigurationError(
                "a bound authorization scope requires the durable spend ledger"
            )
        from src.repositories.llm_spend_ledger_repository import (
            SpendIdentityConflict,
            SpendLimitExceeded as LedgerLimitExceeded,
        )

        estimate_cny = reservation_cny(
            prompt_chars=prompt_chars, max_tokens=max_tokens, attempts=attempts
        )
        authorization_id, scope_id = scope
        resolved_call_id = call_id or f"{scope_id}:{purpose}:{uuid.uuid4().hex}"
        try:
            reservation = _ledger.reserve(  # type: ignore[attr-defined]
                call_id=resolved_call_id,
                authorization_id=authorization_id,
                scope_id=scope_id,
                purpose=purpose,
                model=model,
                estimated_micros=math.ceil(estimate_cny * 1_000_000),
                extra={"prompt_chars": int(prompt_chars), "max_tokens": max_tokens,
                       "attempts": int(attempts)},
                account_id=_account_id,
            )
        except (LedgerLimitExceeded, SpendIdentityConflict) as exc:
            raise SpendLimitExceeded(str(exc)) from exc
        if reservation.created:
            # F5: persist the send intent before the request leaves the process.
            _ledger.mark_sent(resolved_call_id)  # type: ignore[attr-defined]
        return reservation.reserved_micros / 1_000_000

    cap = spend_cap_cny()
    if cap is None:
        return 0.0
    reservation = reservation_cny(
        prompt_chars=prompt_chars, max_tokens=max_tokens, attempts=attempts
    )
    global _reserved_cny
    with _lock:
        if _reserved_cny + reservation > cap:
            raise SpendLimitExceeded(
                f"spend cap reached for {purpose}: reserved={_reserved_cny:.4f} "
                f"next={reservation:.4f} cap={cap:.4f} CNY"
            )
        _reserved_cny += reservation
    return reservation
