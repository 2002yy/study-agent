"""CL-M3 M3-QC: one admission gate in front of every real model call in a research round.

Implements Q-10 (double-track accounting) and Q-11 (tool re-validation) of
``docs/CL_M3_CAPABILITY_CONTRACT.md``.

**What this module does not do.** It does not keep a ledger. Logical quota is delegated to
the existing ``SqliteDecisionAdmission`` (restart-safe, ``request_id``-idempotent, and
deliberately without a refund API), and real cost is delegated to a *port* whose only
production implementation lives in the spend-ledger work (#259). Writing a third ledger
here would create two sources of truth for the same money, so the module takes both as
injected collaborators and refuses to run without either.

**Two tracks, never one.** ``reserve`` is called on both tracks before the provider sees
the request. A logical admission that succeeds while the cost ledger fails must not send
the request: the tracks are independent, and the stricter of the two wins.

**Unknown is not free.** A timeout, a cancellation, or a connection that dies after the
request left the process leaves the cost unsettled. Settling that as "refunded" would
report money that was probably spent as money never spent, so the only settlement for an
unresolved call is ``unresolved``, which keeps the reservation. This mirrors the existing
rule in ``conversation_decision_admission`` ("failed or unknown upstream attempts retain
their reservations").

**Replay cannot re-buy.** The request identity is derived from the planning identity
(operation + round + stage) and the provider task name, so replaying the same round maps to
the same ``request_id`` and is rejected by the admission layer instead of consuming quota a
second time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from src.web.semantic_planner import PlanningIdentity

# Settlement outcomes. ``unresolved`` is distinct from ``failed`` on purpose: failed means
# the provider answered with an error we can price, unresolved means we never learned.
SETTLED = "settled"
FAILED = "failed"
UNRESOLVED = "unresolved"

REJECTED_ALREADY_ATTEMPTED = "already_attempted"
REJECTED_BUDGET = "budget_exhausted"
REJECTED_LEDGER = "cost_ledger_refused"


class AdmissionRefused(RuntimeError):
    """Raised before the provider is called: the round may not spend."""


class LedgerPort(Protocol):
    """The real-cost track. Satisfied by the spend-ledger work; never reimplemented here."""

    def reserve(self, request_id: str, *, model: str, max_output_tokens: int) -> str: ...

    def settle(self, request_id: str, *, outcome: str, cost_micros: int) -> None: ...


class LogicalPort(Protocol):
    """The logical track. ``SqliteDecisionAdmission`` already satisfies this shape."""

    def reserve(self, request_id: str, prompt_chars: int, output_tokens: int) -> str: ...


def round_task_name(identity: PlanningIdentity) -> str:
    """The value a caller passes as ``task_name`` so the call is replay-stable."""

    return identity.key


def request_id_for(task_name: str) -> str:
    """Admission key for one real call, or refuse: an unidentifiable call cannot be priced.

    The shape is ``operation#round#stage`` - the same key the planner uses, so replaying a
    round maps to the same id and is refused by the admission layer instead of re-buying
    quota. A task name that does not carry a round is not admitted at all rather than
    being given a random identity, because a random identity would let a retry spend.
    """

    parts = task_name.split("#") if isinstance(task_name, str) else []
    if len(parts) != 3 or not parts[0] or not parts[1].startswith("r") or not parts[2]:
        raise ValueError("call_task_name_not_round_scoped")
    if not parts[1][1:].isdigit():
        raise ValueError("call_task_name_not_round_scoped")
    return task_name


@dataclass(frozen=True)
class AdmittedCall:
    """What the caller is allowed to report afterwards; carries no model output."""

    request_id: str
    outcome: str
    cost_micros: int


class AdmittedCompletion:
    """Wrap a completion so that every real call is admitted, settled, and never re-bought.

    The wrapper is a ``Callable[..., str]`` with the same keyword surface as
    ``configured_completion``, so it can be handed to ``ResearchSemanticSession`` as its
    completion - which is the only place a research round reaches the provider.
    """

    def __init__(
        self,
        completion: Callable[..., str],
        *,
        logical: LogicalPort,
        ledger: LedgerPort,
        model: str,
        price_micros: Callable[[int], int],
        estimate_output_tokens: int = 1400,
    ) -> None:
        self._completion = completion
        self._logical = logical
        self._ledger = ledger
        self._model = model
        self._price = price_micros
        self._estimate = estimate_output_tokens
        self.calls: list[AdmittedCall] = []

    def __call__(
        self,
        *,
        messages: list[dict[str, str]],
        timeout: float,
        task_name: str,
        **_kwargs: Any,
    ) -> str:
        request_id = request_id_for(task_name)
        prompt_chars = sum(len(row.get("content", "")) for row in messages)

        # Both tracks reserve before the provider is touched. A refusal on either track
        # stops the call; the stricter track decides.
        verdict = self._logical.reserve(request_id, prompt_chars, self._estimate)
        if verdict != "reserved":
            self.calls.append(AdmittedCall(request_id, verdict, 0))
            raise AdmissionRefused(verdict)
        if self._ledger.reserve(
            request_id, model=self._model, max_output_tokens=self._estimate
        ) != "reserved":
            self.calls.append(AdmittedCall(request_id, REJECTED_LEDGER, 0))
            raise AdmissionRefused(REJECTED_LEDGER)

        try:
            value = self._completion(
                messages=messages, timeout=timeout, task_name=task_name, **_kwargs
            )
        except TimeoutError:
            # The provider may or may not have billed. Keep the reservation.
            self._settle(request_id, UNRESOLVED, 0)
            raise
        except Exception:
            self._settle(request_id, FAILED, 0)
            raise
        self._settle(request_id, SETTLED, self._price(self._estimate))
        return value

    def _settle(self, request_id: str, outcome: str, cost_micros: int) -> None:
        self._ledger.settle(request_id, outcome=outcome, cost_micros=cost_micros)
        self.calls.append(AdmittedCall(request_id, outcome, cost_micros))


# --- Q-11: USE_TOOL may not bypass the real executor -----------------------------------


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str
    executor: str = ""


def validate_tool_call(
    *,
    action: str,
    tool: str,
    registry: Mapping[str, Any],
    permitted: frozenset[str],
    budget_remaining: int,
    arguments: Mapping[str, Any] | None = None,
) -> ToolDecision:
    """Second check before a proposed tool call reaches an executor.

    Four independent refusals, because each one has a different failure mode: the action is
    not allowed at all, the named tool does not exist, the tool exists but is outside this
    action's permission set, or the call would run past the remaining budget. None of them
    may be inferred from another - in particular "the tool name exists" never implies "this
    action may run it", and a tool that exists under a different action must not be
    substituted.
    """

    if action != "USE_TOOL":
        return ToolDecision(False, "action_not_tool_use")
    if budget_remaining <= 0:
        return ToolDecision(False, "budget_exhausted")
    executor = registry.get(tool)
    if executor is None:
        return ToolDecision(False, "unknown_tool")
    if tool not in permitted:
        return ToolDecision(False, "tool_not_permitted")
    if arguments is not None and not isinstance(arguments, Mapping):
        return ToolDecision(False, "arguments_not_a_mapping")
    return ToolDecision(True, "permitted", executor=str(tool))
