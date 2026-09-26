"""§102 P2-A2d-2 generic bounded reader-chain executor.

The execution skeleton for Progressive Reader: attempt a backend, persist that
attempt's outcome, ask the routing authority what to do next, and continue - with
a termination bound that comes from the data rather than from a magic number.

::

    candidate
        -> schedulable_now()            (pre-attempt: which backend may run)
        -> execute backend              (one real attempt)
        -> record (candidate, backend)  (history first, always)
        -> route()                      (post-outcome: what next)
             resolve / block_run / defer / exhaust  -> stop
             try_backend(next)                      -> loop

Termination
-----------

There is deliberately no ``MAX_CHAIN_STEPS``. The natural bound is:

    a backend is really attempted at most once per candidate

so the loop can execute at most ``len(chain)`` backends. ``attempted_backends``
is updated **inside** the loop, immediately after each step, so a router can never
re-select a backend that this same invocation already ran. A loop bound derived
from ``len(chain)`` exists only as a safety net against a contract-violating
router; hitting it is reported as ``router_repeated_backend``, not silently
retried.

Two phases stay separate
------------------------

Pre-attempt scheduling and post-outcome routing are different questions, so this
module calls both rather than merging them: ``schedulable_now`` decides the first
backend, ``route`` decides every next one.

Scope
-----

The executor **executes backends and records outcomes**. It never writes evidence,
support or the Gate, keeps no durable state of its own, and adds no ledger. Retry
stays inside a backend: a network retry is not a chain step. ``chain_step`` is an
invocation-local ordinal and never a durable identity - that remains
``(candidate_id, backend)``.

This slice is deliberately production-inert: nothing in the runtime calls it yet,
so the active chain stays exactly what it is today until the atomic cutover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from src.web.research.progressive_routing import (
    ACTION_BLOCK_RUN,
    ACTION_DEFER,
    ACTION_EXHAUST,
    ACTION_RESOLVE,
    ACTION_SCHEDULE,
    ACTION_TRY_BACKEND,
    BackendAvailability,
    BackendCapability,
    RoutingContext,
    SchedulingContext,
    route,
    schedulable_now,
)

REASON_NO_EXECUTOR = "no_executor_for_backend"
REASON_ROUTER_REPEATED_BACKEND = "router_repeated_backend"
REASON_STEP_BOUND_REACHED = "step_bound_reached"


class BackendExecutor(Protocol):
    """One backend's ability to perform a single attempt."""

    name: str

    def execute(self, request: "ChainAttemptRequest") -> "ChainStepResult":
        ...


@dataclass(frozen=True)
class ChainAttemptRequest:
    """What one backend attempt is told. Invocation-local, never durable."""

    candidate_id: str
    url: str
    host: str
    backend: str
    chain_step: int
    outer_attempt_number: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "url": self.url,
            "host": self.host,
            "backend": self.backend,
            "chain_step": self.chain_step,
            "outer_attempt_number": self.outer_attempt_number,
        }


@dataclass(frozen=True)
class ChainStepResult:
    """One backend attempt's outcome, as the executor reports it."""

    backend: str
    retrieval_state: str
    attempted: bool = True
    usable_content: bool = False
    content: str = ""
    adequacy_reason: str = ""
    cost: Mapping[str, Any] = field(default_factory=dict)
    policy: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "retrieval_state": self.retrieval_state,
            "attempted": bool(self.attempted),
            "usable_content": bool(self.usable_content),
            "adequacy_reason": self.adequacy_reason,
            "cost": dict(self.cost),
        }


@dataclass(frozen=True)
class ChainStep:
    """The record of one step actually taken in this invocation."""

    chain_step: int
    outer_attempt_number: int
    backend: str
    retrieval_state: str
    attempted: bool
    usable_content: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_step": self.chain_step,
            "outer_attempt_number": self.outer_attempt_number,
            "backend": self.backend,
            "retrieval_state": self.retrieval_state,
            "attempted": bool(self.attempted),
            "usable_content": bool(self.usable_content),
        }


@dataclass(frozen=True)
class ChainRun:
    """The whole invocation: steps taken, and how the chain ended."""

    candidate_id: str
    steps: tuple[ChainStep, ...]
    action: str
    reason: str = ""
    final_state: str = ""
    terminal: bool = False
    usable_content: bool = False
    attempted_backends: tuple[str, ...] = ()
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "steps": [item.to_dict() for item in self.steps],
            "action": self.action,
            "reason": self.reason,
            "final_state": self.final_state,
            "terminal": bool(self.terminal),
            "usable_content": bool(self.usable_content),
            "attempted_backends": list(self.attempted_backends),
        }


def run_chain(
    *,
    candidate_id: str,
    url: str,
    host: str,
    outer_attempt_number: int,
    chain: Sequence[str],
    executors: Mapping[str, BackendExecutor],
    record_outcome: Callable[[ChainStepResult], None],
    attempted_backends: Sequence[str] = (),
    health_state_for: Callable[[str, str], str] | None = None,
    availability: Mapping[str, BackendAvailability] | None = None,
    backends: Sequence[BackendCapability] | None = None,
    run_blocked: bool = False,
) -> ChainRun:
    """Run one candidate through the chain, bounded by real attempts.

    ``record_outcome`` is called for every **real** attempt and never for a policy
    skip, and it is called *before* the next routing decision so the router and
    candidate resolution always see the same history.
    """

    chain_tuple = tuple(dict.fromkeys(str(item) for item in chain if str(item)))
    attempted: list[str] = list(dict.fromkeys(str(item) for item in attempted_backends))
    visited: set[str] = set()
    steps: list[ChainStep] = []
    content = ""

    def finish(
        action: str,
        *,
        reason: str = "",
        final_state: str = "",
        terminal: bool = False,
        usable: bool = False,
    ) -> ChainRun:
        return ChainRun(
            candidate_id=candidate_id,
            steps=tuple(steps),
            action=action,
            reason=reason,
            final_state=final_state,
            terminal=terminal,
            usable_content=usable,
            attempted_backends=tuple(attempted),
            content=content,
        )

    # Phase 1: which backend may run first?
    scheduling = schedulable_now(
        SchedulingContext(
            candidate_id=candidate_id,
            available_backends=chain_tuple,
            attempted_backends=tuple(attempted),
            host=host,
            run_blocked=run_blocked,
            availability=availability,
        ),
        backends=backends,
        health_state_for=health_state_for,
    )
    if scheduling.action != ACTION_SCHEDULE:
        return finish(scheduling.action, reason=scheduling.reason)

    current = scheduling.backend

    # Phase 2: bounded execution loop. The bound is derived, not configured:
    # a backend may really run at most once, so len(chain) + 1 is already more
    # than the data allows and only guards against a contract-violating router.
    for step_index in range(len(chain_tuple) + 1):
        if current in visited:
            return finish(ACTION_EXHAUST, reason=REASON_ROUTER_REPEATED_BACKEND)
        executor = executors.get(current)
        if executor is None:
            return finish(ACTION_EXHAUST, reason=REASON_NO_EXECUTOR)
        visited.add(current)

        result = executor.execute(
            ChainAttemptRequest(
                candidate_id=candidate_id,
                url=url,
                host=host,
                backend=current,
                chain_step=step_index,
                outer_attempt_number=outer_attempt_number,
            )
        )
        if result.attempted:
            # History first: the outcome exists before anyone routes on it.
            record_outcome(result)
            if current not in attempted:
                attempted.append(current)
            content = result.content or content
        steps.append(
            ChainStep(
                chain_step=step_index,
                outer_attempt_number=outer_attempt_number,
                backend=current,
                retrieval_state=result.retrieval_state,
                attempted=bool(result.attempted),
                usable_content=bool(result.usable_content),
            )
        )

        decision = route(
            RoutingContext(
                candidate_id=candidate_id,
                current_backend=current,
                retrieval_state=result.retrieval_state,
                adequacy_reason=result.adequacy_reason,
                attempted=bool(result.attempted),
                attempted_backends=tuple(attempted),
                available_backends=chain_tuple,
                host=host,
                availability=availability,
            ),
            backends=backends,
            health_state_for=health_state_for,
        )
        if decision.action == ACTION_RESOLVE:
            return finish(
                ACTION_RESOLVE,
                reason=decision.reason,
                final_state=decision.to_dict()["reason"],
                terminal=True,
                usable=bool(decision.usable_content or result.usable_content),
            )
        if decision.action in (ACTION_BLOCK_RUN, ACTION_DEFER, ACTION_EXHAUST):
            return finish(
                decision.action,
                reason=decision.reason,
                final_state=result.retrieval_state,
            )
        if decision.action != ACTION_TRY_BACKEND:
            return finish(ACTION_EXHAUST, reason=REASON_STEP_BOUND_REACHED)
        if decision.next_backend in visited:
            return finish(ACTION_EXHAUST, reason=REASON_ROUTER_REPEATED_BACKEND)
        current = decision.next_backend

    return finish(ACTION_EXHAUST, reason=REASON_STEP_BOUND_REACHED)


__all__ = [
    "REASON_NO_EXECUTOR",
    "REASON_ROUTER_REPEATED_BACKEND",
    "REASON_STEP_BOUND_REACHED",
    "BackendExecutor",
    "ChainAttemptRequest",
    "ChainRun",
    "ChainStep",
    "ChainStepResult",
    "run_chain",
]
